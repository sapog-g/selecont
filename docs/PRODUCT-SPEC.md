# Product specification

## Product promise

selecont lets one person maintain one identity while choosing the right context for each part of their social life.

The core use case is simple: a student wants to share a joke with friends, a family moment with relatives and a project update with colleagues. Those audiences should not require three accounts, and they should not be forced into one undifferentiated feed.

## Core model

An **author** owns one public context and can create private circles. Each circle connects three things:

1. a profile variant with its own photo and bio;
2. access to selected posts;
3. a separate discussion under those posts.

One post may target several circles. The post and its like count are shared, while comments and replies stay inside the viewer's current audience.

## Roles

| Viewer | Profile | Posts | Discussion |
|---|---|---|---|
| Anonymous | Public variant | Public only | Read public thread |
| Registered outside a circle | Public variant | Public only | Use public thread |
| Follower in a circle | Circle variant | Public plus posts for that circle | General and/or private thread, depending on the post |
| Author | Manages all variants | Manages own posts and audiences | Reviews each audience separately |

Following an author does not grant private access. The author explicitly assigns a follower to a circle, and each follower can belong to at most one private circle for that author.

## Current prototype

The local demo supports:

- separate authenticated accounts and anonymous viewing;
- author-created circles and follower assignment;
- independent profile variants;
- explicit multi-audience publishing;
- one optional image per post;
- nested replies up to 12 levels;
- comment deletion that preserves the reply tree;
- one like per user and a shared count;
- audience preview and current-access rechecks;
- access revocation for pages, discussions and media.

## Privacy rules

- Empty audience selection never means “everyone”.
- A viewer never supplies a trusted circle identifier for normal reading or interaction.
- Names and membership lists of hidden circles are not exposed to viewers.
- A reply must remain in the same post and audience as its parent.
- Private media is not stored in a public static directory.
- Removing a member blocks subsequent requests made with old URLs or an existing session.
- Delivered content cannot be technically recalled from screenshots, downloads or human memory.

## Deliberate exclusions

The current prototype does not include public registration, password recovery, notifications, direct messages, moderation tools, blocking, albums, video or mobile apps. These are later product layers and should not weaken the core context model during validation.

## Next validation step

The next milestone is to recruit first participants and answer three questions:

1. Do people recognize situations in which they want to share something with only part of their social graph?
2. Can they configure circles and publish without explanation?
3. Do they return to use the same contexts again?
