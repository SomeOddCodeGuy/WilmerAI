## Quick Guide to Understanding Memories in WilmerAI

### What are the memories?

Wilmer memories, at the time of this writing (2024-11-30), are primarily made up of two components:

* A memory file, which takes your conversation, breaks it into chunks, and writes summaries of it
* A chat summary file, which takes the memories above and summarizes those into a small story-form summary
  of everything that has been said up to now.

### How do you create the memories?

In order for Wilmer memories to be triggered, somewhere in your discussion must be a [DiscussionId].
You can read more about DiscussionId tags
[on this quick guide](SillyTavern.md#step-6-you-should-be-good-to-go-but-if-you-want-memoriessummaries-read-this) and
on the [main readme here](../../README.md#understanding-memories).

When Wilmer find a DiscussionId tag, that activates a whole line of options within Wilmer. It will next
look for certain nodes in the workflow to trigger them. Right now, the main node to do this is the [Chat
Summary node](../../README.md#full-chat-summary-node), which triggers the generation of memories and a chat summary,
and then returns the summary. You can also pull the memories, without triggering them to be written, with the
[recent memory summarizer node](../../README.md#recent-memory-summarizer-tool).

### Why do some nodes make memories, and some nodes just pull them?

Why would you want one node to trigger generating memories and one not to? The answer comes down to managing
response performance.

Wilmer has a concept of "Workflow Locks". You can [read more about them here](../../README.md#workflow-lock), but
the short version is that if you have a workflow with a lock on it, the workflow will engage the lock when the lock
is reached. If you then try sending another prompt to the same workflow, if that lock is still engaged then the workflow
won't go past that point.

Lets consider an
[example workflow](../../Public/Configs/Workflows/convo-roleplay-dual-model/FullCustomWorkflow-ChatSummary-WorkflowLocked.json).
The steps of this workflow are (as of 2024-11-30):

* Get the chat summary without generating or updating the chat summary file
* Respond to the user using the chat summary file
* Workflow lock
* Update the memories and chat summary

Now, part of this user being "dual model" is to give you the option of having each model on a different computer. Why?
One model is the "responder" and the other writes memories.

So say you send a prompt to this workflow. It will pull the summary, Model #1 will respond to you, the lock will engage,
and Model #2 will begin working on writing memories and chat summaries.

If you then send another prompt right after, while Model #2 is still working? You'll get the chat summary, Model #1 will
respond to the user... and the workflow will stop.

This means that you can keep chatting away with Model #1, while Model #2 works quietly in the background to keep your
memories and chat summary up to date.

### Understanding the memory and chat summary files

If you peek inside the files, you'll notice that they are a json format that contains 1 or more pairs of text, looking
something like this:

```json
[
  {
    "text_block": "This is a memory",
    "hash": "This is the hash of the last message in the chunk tied to the memory"
  }
]
```

A memory is basically a summary of a chunk of messages. So if there are 10 messages, a memory might be made up of 5 of
those. The LLM is given the messages, as well as the prompt specified in the
"_DiscussionId-MemoryFile-Workflow-Settings" json file in your workflow folder, and it summarizes those messages.
Wilmer then writes the memory to the text_block file, and will then hash message #5 and put that hash alongside
the memory.

What this does is tell Wilmer where the memory ends, so that it knows where the next memory begins. Wilmer can also use
this to figure out how many messages ago you last made a memory.

Chat summaries work the same way, except there is only 1 text block and hash; the hash will be the same as the last
memory it included in the summary.

Memories are automatically created as you go, and the chat summary is automatically updated as you go. As long as you
have the node in your workflow and a discussionid, you shouldn't need to be do anything with them.

### Cleaning up memories

With that said, there are a couple of tricks with memories to improve quality. In particular, if you delete the memory
file, or you delete a few memories starting at the end of the file, Wilmer will regenerate them on the next run.

Note- you will also want to delete your chat summary if you do this; Wilmer might do weird things if you only mess with
the memory file. Your summary could end up looking really funky.

A couple of reasons you may want to delete the memory file are:

* You modified some messages early on and want to capture that information
* You redid the prompts in the memory settings and want the memories rebuilt using those prompts
* You want to consolidate memories

On the last point: if you're looking at the memory settings, you'll see this:

```json
{
  "maxResponseSizeInTokens": 250,
  "chunkEstimatedTokenSize": 2500,
  "maxMessagesBetweenChunks": 20,
  "lookbackStartTurn": 7
}
```

Chunk estimated token size is 2500 and maxMessagesBetweenChunks is 20. Say that you've been chatting for a while
and it has generated 10 memories, even though all your messages were pretty short. The reason may be that each memory
was triggered to be made because of maxMessagesBetweenChunks; no matter what, it kept generating a new memory every 20
messages.

If you delete the memory file and re-run it, Wilmer will prioritize instead the chunkEstimatedTokenSize, and will ignore
the max message limit for old messages (it will still use that limit for new messages that come in later). Because of
this, if that limit caused each of your memories to be made with only 500 tokens worth of messages, you might get
memories made up of 5x larger chunks of messages with this, reducing your 10 memories down to 2 or 3.