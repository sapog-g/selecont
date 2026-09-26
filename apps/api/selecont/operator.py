"""Local operator actions for the closed demo; never mounted as web routes."""

from .auth import AuthStore
from .core import NotFound, Store


DEMO_HANDLES = ("grigory", "friend", "family", "stranger")


def provision_user(database, handle, password, *, replace_password=False):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    store = Store(database)
    try:
        store.migrate()
        try:
            user_id = store.user_id_for_handle(handle)
        except NotFound:
            user_id = store.create_user(handle)
    finally:
        store.close()
    with AuthStore(database) as auth:
        auth.set_password(user_id, password, replace=replace_password)
    return user_id


def seed_demo(database, password, *, replace_password=False):
    ids = {
        handle: provision_user(database, handle, password, replace_password=replace_password)
        for handle in DEMO_HANDLES
    }
    store = Store(database)
    try:
        contexts = store.author_contexts(ids["grigory"], ids["grigory"])
        by_name = {row["name"]: row["id"] for row in contexts}
        friends = by_name.get("Friends") or store.create_circle(ids["grigory"], "Friends")
        family = by_name.get("Family") or store.create_circle(ids["grigory"], "Family")
        public = next(row["id"] for row in store.author_contexts(ids["grigory"], ids["grigory"]) if row["kind"] == "public")
        store.set_profile(ids["grigory"], public, bio="A second-year ITMO student building selecont.")
        store.set_profile(ids["grigory"], friends, bio="Campus life, jokes and late-night plans.")
        store.set_profile(ids["grigory"], family, bio="Study, home and the people closest to me.")
        store.follow(ids["friend"], ids["grigory"])
        store.follow(ids["family"], ids["grigory"])
        store.assign(ids["grigory"], ids["friend"], friends)
        store.assign(ids["grigory"], ids["family"], family)
        return ids
    finally:
        store.close()


def revoke_demo_member(database, author_handle, follower_handle):
    store = Store(database)
    try:
        store.migrate()
        author_id = store.user_id_for_handle(author_handle)
        follower_id = store.user_id_for_handle(follower_handle)
        store.revoke(author_id, follower_id)
    finally:
        store.close()
