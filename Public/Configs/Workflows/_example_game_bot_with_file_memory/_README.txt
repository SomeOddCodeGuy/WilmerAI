This example is a game bot backed by file-based memory. It is meant for anything from a one-on-one
persona chat to a multi-character story to a tabletop-style game master. It works best with a frontend that sends the
persona names in the prompt (SillyTavern does this by default; others may as well).

The workflow reads the recent messages, updates and reads its long-term memory, analyzes the current scene and its
backstory, works out which character speaks next, and then writes the response with a larger model. The heavy lifting
(analysis, extraction) runs on a fast worker model; only the final response uses the large responder model.

--- Setup ---

1. Open the user file (_example_game_bot_with_file_memory.json) and set discussionDirectory and sqlLiteDirectory to a
   folder of your choice, or leave them blank to default to the Public directory. This workflow requires a
   [DiscussionId] tag in a user or system message. Without it, discussion-directory resolution raises an error
   before the initial file reads. Keep the same ID across turns that should share memory.

2. The workflow reads three plain-text files from `{Discussion_Directory}`, the same canonical per-discussion directory
   used by WilmerAI's built-in memories and summaries. Do not add a `gameTempDir` variable. All three files are optional;
   if a file is missing or empty the workflow still runs, it just has less context to work with. Make one request first
   so the directory is created, then add the files you want:

   - character_guidance.txt : How the NPCs behave and speak: reaction tendencies, speech styles, personality notes,
     and any house rules for the game. This is injected into every analysis step and the final response.
   - world_info.txt         : Static background about the setting: locations, factions, populations, lore. Facts that
     are true about the world and do not change on their own.
   - key_events.md          : A running list of the notable events you never want the bot to lose track of, such as
     "The dwarves found titanium in the toe of a giant's boot and mined it." The rolling story summary keeps the broad
     narrative, but small facts that matter to a single character tend to get washed out of it; this file is where you
     keep them. In this file-memory example you maintain it by hand. It is read on every turn.

   The resolved directory is `<discussionDirectory>/<DiscussionId>/`, or
   `<discussionDirectory>/<API-key-hash>/<DiscussionId>/` when the request supplies an Authorization Bearer key.
   Clients that use a Bearer key must keep using the same key for that discussion. Different clients should use
   different high-entropy keys when their discussion IDs might overlap. A Bearer value supplies a storage namespace;
   WilmerAI does not validate it as a login credential by itself.

3. Memory is generated automatically as the game runs. The long-term memory file (chronological story summaries), the
   rolling chat summary, and automatic condensation of older memories into denser ones are all configured in
   _DiscussionId-MemoryFile-Workflow-Settings.json. Condensation is on by default so the memory file stays a manageable
   size over very long sessions.

4. Existing installations require a one-time manual move. The old `gameTempDir` was shared by every discussion. Copy
   each of its three files into every canonical discussion directory that should use those contents. Do not keep the old
   shared path in these workflow files, because doing so bypasses API-key storage isolation.

--- Endpoints ---

All endpoints come from the _example_users endpoint set. Point them at your own models before running:

   - Worker-Endpoint            : the fast analysis and extraction steps.
   - Responder-Endpoint         : the final written response.
   - Memory-Generation-Endpoint : creating, summarizing, and condensing memories.

--- Frontend note ---

If you are using something like Open WebUI, open the user file and set chatCompleteAddUserAssistant and
chatCompletionAddMissingAssistantGenerator to true. Leave them off for SillyTavern and similar.
