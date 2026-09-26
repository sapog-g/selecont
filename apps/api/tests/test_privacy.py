"""Security regressions against real SQLite, independent of any UI."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selecont.core import (
    AuthenticationRequired,
    InvalidInput,
    MAX_COMMENT_DEPTH,
    MAX_COMMENTS_PER_THREAD,
    NotFound,
    Store,
)


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.store = Store(self.path)
        self.store.migrate()
        self.author, self.friend, self.family, self.stranger, self.other = [
            self.store.create_user(name) for name in ('grigory', 'friend', 'family', 'stranger', 'other')
        ]
        self.public = next(c['id'] for c in self.store.author_contexts(self.author, self.author) if c['kind'] == 'public')
        self.friends = self.store.create_circle(self.author, 'Друзья')
        self.families = self.store.create_circle(self.author, 'Семья')
        for user, circle in [(self.friend, self.friends), (self.family, self.families)]:
            self.store.follow(user, self.author)
            self.store.assign(self.author, user, circle)
        for circle, bio, avatar in [(self.public, 'Public bio', 'public-photo'), (self.friends, 'Friends bio', 'friends-photo'), (self.families, 'Family bio', 'family-photo')]:
            self.store.set_profile(self.author, circle, bio=bio, avatar_key=avatar)
        self.shared = self.store.publish(self.author, 'Passed my last exam', [self.friends, self.families])
        self.private = self.store.publish(self.author, 'Friends only', [self.friends])
        self.public_post = self.store.publish(self.author, 'Public post', [self.public])

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_variants_and_hidden_metadata(self):
        for viewer, bio in [(None, 'Public bio'), (self.stranger, 'Public bio'), (self.friend, 'Friends bio'), (self.family, 'Family bio')]:
            value = self.store.profile(self.author, viewer)
            self.assertEqual(value['bio'], bio)
            self.assertEqual(set(value), {'handle', 'bio', 'avatar_key'})

    def test_shared_post_is_one_object_with_separate_branches(self):
        self.store.add_comment(self.friend, self.shared, 'Celebrate!', channel='private')
        self.store.add_comment(self.family, self.shared, 'Proud of you', channel='private')
        friend = self.store.thread(self.shared, self.friend, channel='private')
        family = self.store.thread(self.shared, self.family, channel='private')
        self.assertEqual([x['body'] for x in friend['comments']], ['Celebrate!'])
        self.assertEqual([x['body'] for x in family['comments']], ['Proud of you'])
        self.assertEqual(self.store.post(self.shared, self.friend)['id'], self.store.post(self.shared, self.family)['id'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM posts WHERE id = ?', (self.shared,)).fetchone()[0], 1)

    def test_reactions_are_global_per_post_and_idempotent(self):
        self.store.react(self.friend, self.shared)
        self.store.react(self.friend, self.shared)
        self.assertEqual(self.store.thread(self.shared, self.friend, channel='private')['reaction_count'], 1)
        self.assertEqual(self.store.thread(self.shared, self.family, channel='private')['reaction_count'], 1)
        self.store.react(self.family, self.shared)
        self.assertEqual(self.store.thread(self.shared, self.friend, channel='private')['reaction_count'], 2)
        self.store.react(self.friend, self.shared, active=False)
        self.assertEqual(self.store.thread(self.shared, self.friend, channel='private')['reaction_count'], 1)
        self.assertFalse(self.store.has_reacted(self.friend, self.shared))
        self.assertTrue(self.store.has_reacted(self.family, self.shared))

    def test_reaction_identities_and_current_circle_are_author_only(self):
        self.store.react(self.friend, self.shared)
        self.store.react(self.family, self.shared)
        reactions = self.store.author_reactions(self.author, self.shared)
        self.assertEqual(
            {(row['handle'], row['context_name']) for row in reactions},
            {('friend', 'Друзья'), ('family', 'Семья')},
        )
        with self.assertRaises(NotFound):
            self.store.author_reactions(self.friend, self.shared)
        self.store.revoke(self.author, self.friend)
        reactions = self.store.author_reactions(self.author, self.shared)
        self.assertIn(('friend', 'No private circle'), {(row['handle'], row['context_name']) for row in reactions})

    def test_public_and_private_are_explicit_channels(self):
        post = self.store.publish(self.author, 'Both', [self.public, self.friends])
        self.store.add_comment(self.friend, post, 'Public message', channel='public')
        self.store.add_comment(self.friend, post, 'Private message', channel='private')
        self.assertEqual(self.store.post(post, self.friend)['channels'], ['public', 'private'])
        self.assertEqual([x['body'] for x in self.store.thread(post)['comments']], ['Public message'])
        self.assertEqual(self.store.post(post, self.family)['channels'], ['public'])

    def test_anonymous_can_read_public_but_cannot_act(self):
        self.assertEqual(self.store.profile(self.author)['bio'], 'Public bio')
        self.assertEqual(self.store.post(self.public_post)['body'], 'Public post')
        for action in [lambda: self.store.add_comment(None, self.public_post, 'no'), lambda: self.store.react(None, self.public_post), lambda: self.store.follow(None, self.author)]:
            with self.assertRaises(AuthenticationRequired): action()

    def test_private_urls_and_unknown_ids_are_indistinguishable(self):
        for post in [self.shared, self.private, 'missing']:
            for viewer in [None, self.stranger]:
                with self.assertRaises(NotFound): self.store.post(post, viewer)
                with self.assertRaises(NotFound): self.store.thread(post, viewer)

    def test_no_public_branch_created_by_private_intersection(self):
        with self.assertRaises(NotFound): self.store.thread(self.shared, self.friend, channel='public')

    def test_injecting_context_or_author_preview_fails(self):
        for action in [
            lambda: self.store.thread(self.shared, self.friend, channel=self.families),
            lambda: self.store.thread(self.shared, self.friend, author_context=self.families),
            lambda: self.store.add_comment(self.friend, self.shared, 'attack', author_context=self.families),
            lambda: self.store.profile(self.author, self.friend, preview_context=self.families),
            lambda: self.store.author_contexts(self.friend, self.author),
        ]:
            with self.assertRaises(NotFound): action()

    def test_author_can_preview_and_answer_both_contexts(self):
        for circle, body in [(self.friends, 'Friends reply'), (self.families, 'Family reply')]:
            self.store.add_comment(self.author, self.shared, body, author_context=circle)
        self.assertEqual(self.store.profile(self.author, self.author, preview_context=self.families)['bio'], 'Family bio')
        self.assertEqual([c['body'] for c in self.store.thread(self.shared, self.friend, channel='private')['comments']], ['Friends reply'])
        self.assertEqual([c['body'] for c in self.store.thread(self.shared, self.author, author_context=self.families)['comments']], ['Family reply'])

    def test_follow_does_not_grant_membership(self):
        self.store.follow(self.stranger, self.author)
        self.assertEqual(self.store.profile(self.author, self.stranger)['bio'], 'Public bio')
        with self.assertRaises(NotFound): self.store.post(self.shared, self.stranger)

    def test_membership_requires_follow_and_is_single_per_author(self):
        with self.assertRaises(NotFound): self.store.assign(self.author, self.stranger, self.friends)
        self.store.assign(self.author, self.friend, self.families)
        self.assertEqual(self.store.profile(self.author, self.friend)['bio'], 'Family bio')
        with self.assertRaises(NotFound): self.store.post(self.private, self.friend)
        count = self.store.db.execute('SELECT COUNT(*) FROM memberships WHERE author_id = ? AND follower_id = ?', (self.author, self.friend)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_two_authors_can_assign_same_follower_independently(self):
        circle = self.store.create_circle(self.other, 'Other circle')
        self.store.follow(self.friend, self.other)
        self.store.assign(self.other, self.friend, circle)
        self.store.set_profile(self.other, circle, bio='Other author bio')
        self.assertEqual(self.store.profile(self.author, self.friend)['bio'], 'Friends bio')
        self.assertEqual(self.store.profile(self.other, self.friend)['bio'], 'Other author bio')

    def test_revoke_blocks_existing_connection_and_own_old_comments(self):
        comment = self.store.add_comment(self.friend, self.shared, 'Old', channel='private')
        previous_connection = Store(self.path)
        self.addCleanup(previous_connection.close)
        previous_connection.thread(self.shared, self.friend, channel='private')
        self.store.revoke(self.author, self.friend)
        for action in [
            lambda: previous_connection.post(self.shared, self.friend),
            lambda: previous_connection.thread(self.shared, self.friend, channel='private'),
            lambda: previous_connection.add_comment(self.friend, self.shared, 'After revoke', channel='private'),
            lambda: previous_connection.react(self.friend, self.shared),
            lambda: previous_connection.delete_comment(self.friend, comment),
        ]:
            with self.assertRaises(NotFound): action()
        self.assertEqual(previous_connection.profile(self.author, self.friend)['bio'], 'Public bio')
        self.assertEqual(previous_connection.post(self.public_post, self.friend)['body'], 'Public post')

    def test_old_comments_stay_in_old_context_when_moved(self):
        self.store.add_comment(self.friend, self.shared, 'Old private text', channel='private')
        self.store.assign(self.author, self.friend, self.families)
        self.assertEqual(self.store.thread(self.shared, self.friend, channel='private')['comments'], [])
        self.store.assign(self.author, self.friend, self.friends)
        self.assertEqual(self.store.thread(self.shared, self.friend, channel='private')['comments'][0]['body'], 'Old private text')

    def test_unfollow_revokes_membership(self):
        self.store.unfollow(self.friend, self.author)
        with self.assertRaises(NotFound): self.store.post(self.shared, self.friend)
        self.store.follow(self.friend, self.author)
        with self.assertRaises(NotFound): self.store.post(self.shared, self.friend)

    def test_lists_filter_private_posts_without_counts_or_contexts(self):
        self.assertEqual([p['id'] for p in self.store.list_posts(self.author)], [self.public_post])
        self.assertEqual({p['id'] for p in self.store.list_posts(self.author, self.family)}, {self.public_post, self.shared})
        for post in self.store.list_posts(self.author, self.friend):
            self.assertEqual(set(post), {'id', 'body', 'created_at'})

    def test_cross_author_circle_rejected_before_writes(self):
        other_circle = self.store.create_circle(self.other, 'Other')
        for action in [lambda: self.store.publish(self.author, 'No', [self.friends, other_circle]), lambda: self.store.assign(self.author, self.friend, other_circle), lambda: self.store.set_profile(self.author, other_circle, bio='No')]:
            with self.assertRaises(NotFound): action()
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM posts WHERE body = 'No'").fetchone()[0], 0)

    def test_database_foreign_keys_reject_cross_author_audiences_and_variants(self):
        other_circle = self.store.create_circle(self.other, 'Other')
        for sql, values in [
            ('INSERT INTO post_audiences VALUES (?, ?, ?)', (self.author, self.private, other_circle)),
            ('INSERT INTO profile_variants(author_id, context_id) VALUES (?, ?)', (self.author, other_circle)),
            ('UPDATE memberships SET context_id = ? WHERE author_id = ? AND follower_id = ?', (other_circle, self.author, self.friend)),
        ]:
            with self.assertRaises(sqlite3.IntegrityError): self.store.db.execute(sql, values)

    def test_public_cannot_be_used_as_membership(self):
        with self.assertRaises(InvalidInput): self.store.assign(self.author, self.friend, self.public)
        with self.assertRaises(sqlite3.IntegrityError): self.store.db.execute('UPDATE memberships SET context_id = ? WHERE follower_id = ?', (self.public, self.friend))

    def test_public_variant_and_circle_copy_exist(self):
        circle = self.store.create_circle(self.author, 'New')
        self.assertEqual(self.store.profile(self.author, self.author, preview_context=circle)['bio'], 'Public bio')
        self.store.set_profile(self.author, self.public, bio='Changed public')
        self.assertEqual(self.store.profile(self.author, self.author, preview_context=circle)['bio'], 'Public bio')

    def test_delete_post_checks_author_and_removes_all_threads(self):
        self.store.add_comment(self.friend, self.shared, 'Delete me', channel='private')
        self.store.react(self.family, self.shared)
        with self.assertRaises(NotFound): self.store.delete_post(self.friend, self.shared)
        self.store.delete_post(self.author, self.shared)
        for table in ['post_audiences', 'comments', 'reactions']:
            self.assertEqual(self.store.db.execute(f'SELECT COUNT(*) FROM {table} WHERE post_id = ?', (self.shared,)).fetchone()[0], 0)
        with self.assertRaises(NotFound): self.store.thread(self.shared, self.author, author_context=self.friends)

    def test_comment_delete_checks_access_and_authorship(self):
        comment = self.store.add_comment(self.friend, self.shared, 'Mine', channel='private')
        with self.assertRaises(NotFound): self.store.delete_comment(self.family, comment)
        self.store.delete_comment(self.author, comment)
        [deleted] = self.store.thread(self.shared, self.friend, channel='private')['comments']
        self.assertEqual(deleted['id'], comment)
        self.assertEqual(deleted['body'], '')
        self.assertIsNotNone(deleted['deleted_at'])
        with self.assertRaises(NotFound):
            self.store.delete_comment(self.author, comment)
        with self.assertRaises(NotFound):
            self.store.add_comment(
                self.friend, self.shared, 'Reply to tombstone',
                channel='private', parent_id=comment,
            )

    def test_data_survives_reopen_and_migration_is_repeatable(self):
        other_connection = Store(self.path)
        try:
            other_connection.migrate()
            self.assertEqual(other_connection.profile(self.author, self.friend)['bio'], 'Friends bio')
            self.assertEqual(other_connection.post(self.shared, self.family)['body'], 'Passed my last exam')
            self.assertEqual(other_connection.db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        finally: other_connection.close()

    def test_future_schema_is_not_silently_overwritten(self):
        self.store.db.execute('PRAGMA user_version = 999')
        with self.assertRaises(RuntimeError): self.store.migrate()

    def test_invalid_content_and_remote_avatar_urls_rejected(self):
        for action in [lambda: self.store.publish(self.author, '', [self.public]), lambda: self.store.publish(self.author, 'No audience', []), lambda: self.store.set_profile(self.author, self.public, bio='OK', avatar_key='https://example.com/private.png')]:
            with self.assertRaises(InvalidInput): action()

    def test_replies_can_have_multiple_levels(self):
        parent = None
        ids = []
        for level in range(8):
            parent = self.store.add_comment(self.friend, self.shared, f'Level {level}', channel='private', parent_id=parent)
            ids.append(parent)
        thread = self.store.thread(self.shared, self.friend, channel='private')['comments']
        by_id = {c['id']: c for c in thread}
        self.assertIsNone(by_id[ids[0]]['parent_id'])
        for child, parent in zip(ids[1:], ids): self.assertEqual(by_id[child]['parent_id'], parent)

    def test_new_comments_have_depth_and_thread_size_limits(self):
        parent = None
        for level in range(MAX_COMMENT_DEPTH):
            parent = self.store.add_comment(
                self.friend, self.shared, f'Bounded {level}',
                channel='private', parent_id=parent,
            )
        with self.assertRaises(InvalidInput):
            self.store.add_comment(
                self.friend, self.shared, 'Too deep',
                channel='private', parent_id=parent,
            )
        remaining = MAX_COMMENTS_PER_THREAD - MAX_COMMENT_DEPTH
        for number in range(remaining):
            self.store.add_comment(
                self.friend, self.shared, f'Root {number}', channel='private'
            )
        with self.assertRaises(InvalidInput):
            self.store.add_comment(self.friend, self.shared, 'Too many', channel='private')

    def test_reply_parent_must_be_in_same_post_and_context(self):
        family_comment = self.store.add_comment(self.family, self.shared, 'Secret family', channel='private')
        friend_other_post = self.store.add_comment(self.friend, self.private, 'Different post', channel='private')
        for parent in [family_comment, friend_other_post, 'missing']:
            with self.assertRaises(NotFound):
                self.store.add_comment(self.friend, self.shared, 'Attempt', channel='private', parent_id=parent)
        with self.assertRaises(NotFound):
            self.store.add_comment(self.author, self.shared, 'Attempt', author_context=self.friends, parent_id=family_comment)

    def test_database_rejects_cross_context_reply_even_with_valid_post(self):
        parent = self.store.add_comment(self.family, self.shared, 'Family only', channel='private')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute('INSERT INTO comments(id, post_id, context_id, commenter_id, body, parent_id) VALUES (?, ?, ?, ?, ?, ?)',
                                  ('bad-child', self.shared, self.friends, self.friend, 'Attack', parent))

    def test_deleting_comment_preserves_replies_and_other_branches(self):
        parent = self.store.add_comment(self.friend, self.shared, 'Root', channel='private')
        child = self.store.add_comment(self.author, self.shared, 'Author reply', author_context=self.friends, parent_id=parent)
        self.store.add_comment(self.friend, self.shared, 'Grandchild', channel='private', parent_id=child)
        sibling = self.store.add_comment(self.friend, self.shared, 'Independent root', channel='private')
        family = self.store.add_comment(self.family, self.shared, 'Unaffected family', channel='private')
        self.store.delete_comment(self.friend, parent)
        comments = self.store.thread(self.shared, self.friend, channel='private')['comments']
        by_id = {comment['id']: comment for comment in comments}
        self.assertEqual(set(by_id), {parent, child, sibling, next(c['id'] for c in comments if c['body'] == 'Grandchild')})
        self.assertEqual(by_id[parent]['body'], '')
        self.assertIsNotNone(by_id[parent]['deleted_at'])
        self.assertEqual(by_id[child]['body'], 'Author reply')
        self.assertEqual(by_id[child]['parent_id'], parent)
        self.assertEqual([c['id'] for c in self.store.thread(self.shared, self.family, channel='private')['comments']], [family])

    def test_revoked_user_cannot_reply_to_known_parent(self):
        parent = self.store.add_comment(self.friend, self.shared, 'Known', channel='private')
        self.store.revoke(self.author, self.friend)
        with self.assertRaises(NotFound):
            self.store.add_comment(self.friend, self.shared, 'Late reply', channel='private', parent_id=parent)

    def test_author_management_reads_all_own_posts_only(self):
        self.assertEqual({p['id'] for p in self.store.author_posts(self.author, self.author)}, {self.shared, self.private, self.public_post})
        self.assertEqual({a['id'] for a in self.store.author_post(self.author, self.shared)['audiences']}, {self.friends, self.families})
        with self.assertRaises(NotFound): self.store.author_posts(self.friend, self.author)
        with self.assertRaises(NotFound): self.store.author_post(self.other, self.shared)

    def _deep_replies(self, depth=1100):
        # Seed historical data directly: the user-facing service now bounds new
        # trees, while deletion must remain safe for older oversized trees.
        root = parent = str(uuid4())
        rows = [(root, self.shared, self.friends, self.friend, 'Deep root', None)]
        for _ in range(depth - 1):
            child = str(uuid4())
            rows.append((child, self.shared, self.friends, self.friend, 'Deep reply', parent))
            parent = child
        with self.store._transaction(write=True):
            self.store.db.executemany(
                'INSERT INTO comments(id, post_id, context_id, commenter_id, body, parent_id) VALUES (?, ?, ?, ?, ?, ?)',
                rows,
            )
        return root

    def test_soft_delete_deep_root_preserves_history_and_permissions(self):
        root = self._deep_replies()
        sibling = str(uuid4())
        with self.store._transaction(write=True):
            self.store.db.execute(
                'INSERT INTO comments(id, post_id, context_id, commenter_id, body, parent_id) VALUES (?, ?, ?, ?, ?, NULL)',
                (sibling, self.shared, self.friends, self.friend, 'Sibling'),
            )
        family = self.store.add_comment(self.family, self.shared, 'Family', channel='private')
        with self.assertRaises(NotFound):
            self.store.delete_comment(self.family, root)
        self.assertEqual(len(self.store.thread(self.shared, self.friend, channel='private')['comments']), 1101)
        self.store.delete_comment(self.friend, root)
        comments = self.store.thread(self.shared, self.friend, channel='private')['comments']
        self.assertEqual(len(comments), 1101)
        deleted = next(comment for comment in comments if comment['id'] == root)
        self.assertEqual(deleted['body'], '')
        self.assertIsNotNone(deleted['deleted_at'])
        self.assertIn(sibling, {comment['id'] for comment in comments})
        self.assertEqual([c['id'] for c in self.store.thread(self.shared, self.family, channel='private')['comments']], [family])
        self.assertEqual(self.store.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_delete_post_with_deep_replies(self):
        self._deep_replies()
        self.store.add_comment(self.family, self.shared, 'Family', channel='private')
        self.store.react(self.friend, self.shared)
        self.store.delete_post(self.author, self.shared)
        for table in ('comments', 'reactions', 'post_audiences'):
            self.assertEqual(self.store.db.execute(f'SELECT COUNT(*) FROM {table} WHERE post_id = ?', (self.shared,)).fetchone()[0], 0)
        with self.assertRaises(NotFound): self.store.post(self.shared, self.friend)
        self.assertEqual(self.store.post(self.public_post)['body'], 'Public post')
        self.assertEqual(self.store.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_soft_delete_rolls_back_on_storage_error(self):
        root = self._deep_replies(12)
        before = self.store.thread(self.shared, self.friend, channel='private')
        self.store.db.execute(
            "CREATE TEMP TRIGGER simulate_delete_failure BEFORE UPDATE OF body, deleted_at ON comments "
            "WHEN OLD.body = 'Deep root' BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError): self.store.delete_comment(self.friend, root)
        self.assertEqual(self.store.thread(self.shared, self.friend, channel='private'), before)

    def test_comment_waiting_for_revoke_transaction_rechecks_membership(self):
        started = threading.Event()
        result = []
        def worker():
            store = Store(self.path)
            try:
                started.set()
                store.add_comment(self.friend, self.shared, 'Concurrent write', channel='private')
                result.append('unexpected success')
            except Exception as error:
                result.append(type(error))
            finally: store.close()
        thread = threading.Thread(target=worker)
        with self.store._transaction(write=True):
            self.store.db.execute('DELETE FROM memberships WHERE author_id = ? AND follower_id = ?', (self.author, self.friend))
            thread.start()
            self.assertTrue(started.wait(2))
        thread.join(6)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [NotFound])


if __name__ == '__main__':
    unittest.main()
