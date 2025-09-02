## Quick Guide to Setting up SillyTavern with WilmerAI *(Out of Date. Will Update Soon)*

NOTE: Make sure that you already [set up Wilmer-Api](_Getting-Start_Wilmer-Api.md) in order to be able to connect to it.
Choose
a SillyTavern friendly example user.

### Step 1: Download SillyTavern and follow their setup instructions to install it and run it

### Step 2: At the top of SillyTavern is a Plug icon. Click it

* Select Text Completion
* Select Ollama (telling SillyTavern to connect to Wilmer as if it were Ollama)
* Input your connection.

It should look like this:

![Ollama Text Completion Settings](../../Examples/Images/ST_ollama_text_completion_settings.png)

You can also choose KoboldCpp for the connection type, which used to be my favorite. However, Ollama
was recently added in order to allow Wilmer to be extended with multi-modal support, so this is probably
preferable for the future.

### Step 3: At the top of SillyTavern is an "A" icon, next to the plug. Click it

There are 2 sections: Instruct and Context. We want to import settings for both of those.

Each section has an import button. I have marked them in the picture below:

![SillyTavern Import Section](../../Examples/Images/ST_Instruct_Context_Settings.png)

The files you want to import can be found in the [Docs/SillyTavern section of Wilmer's codebase](../../SillyTavern)

> **IMPORTANT**: Yes, Wilmer has an Instruct Template, and it is absolutely important that you import it
> and do not modify it. Wilmer is not like a model that may do ok with a different template. Without this
> template, Wilmer cannot parse the incoming commands and will just straight up break.
>
> **NOTE**: Feel free to modify the Context Template at the top, though. The Instruct Template is the only absolutely
> necessary part.

### Step 4: Ensure on this screen that "Always add character's name to prompt" is checked (top right of above screenshot)

### Step 5: At the far left top, left of the plug icon, is an icon of little dials, where samplers are at. Click it

We don't care about most samplers in here; Wilmer handles all that. What we do care about is that the whole context
gets sent over to Wilmer.

There are 2 things that are important in this screen

* `Stream`: This tells both SillyTavern and Wilmer if you want the text to stream to the screen or not. Most people
  want this.
* `Context(tokens)`: How much context to send to Wilmer. There should be an "unlocked" checkbox near it. Click that,
  and then drag the slider as far right as it will go. Right now the max is about 200,000 tokens. If you can go higher,
  go for it. Wilmer will be handling the proper context going to the LLM, but if this is too low it can't do its job of
  building memories and summaries.

### Step 6: You should be good to go, but if you want memories/summaries, read this.

Memories and summaries in Wilmer are triggered by 2 things:

* The workflow having them in it (Most, if not all, the example users have that)
* Wilmer finding a [DiscussionId] tag somewhere in the conversation.

A DiscussionId might look something like this: `[DiscussionId]12345[/DiscussionId]`.
If Wilmer sees that, it will strip it out of the conversation so that the LLM doesn't see it, and will use
it to make memory files and other stuff.

I recommend putting this in the author's note. Sticking it in a persona card will cause every conversation with
that persona to share the same memories.

One neat trick with ST is that you can use the {{char}} command to help identify memory files easily.
One possible naming scheme is `[DiscussionId]{{char}}_2024-11-30[/DiscussionId]` or something like that.