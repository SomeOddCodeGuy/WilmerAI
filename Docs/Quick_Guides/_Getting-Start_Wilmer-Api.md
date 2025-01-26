## Quick Guide to Setting up WilmerAI

### Step 1: Download Wilmer and unzip it somewhere. Navigate to that folder

### Step 2: [Pick a pre-made user](../../README.md#step-2-fast-route-use-pre-made-users)

Short version desc of each:

* `Assistant Multi-Model`: Good for SillyTavern. Prompts are routed to categories, each category
  gets its own workflow and LLM.
* `Assistant Single-Model`: Similar as above, but just 1 model. Each category gets its own workflow,
  so this still has value (like coding specific workflows or reasoning workflows)
* `Convo-Roleplay-Single-Model`: No routing. All messages go to 1 workflow, which is good for regular ol'
  chattin with an LLM.
* `Convo-Roleplay-Dual-Model`: Same as above, but uses 2 models. The second model will be used for generating
  memories and chat summaries. Great if you have 2 computers, as one can work quietly on making memories while
  the other keeps chatting with ya uninterrupted.
* `Group-Chat-Example`: Neat concept user for showing how to do group chats in sillytavern where each persona is a
  different LLM
* `OpenWebUI-Routing-Multi-Model`: Same as assistant multi-model except it has prompts tailored for OpenWebUI. That
  app doesn't do personas, so some of the instructions of other pre-made users confused it.
* `OpenWebUI-Routing-Single-Model`: Same as assistant single-model but for Open-WebUI
* `OpenWebUI-NoRouting-Single-Model`: Same as convo-roleplay single model, but for Open-WebUI
* `OpenWebUI-NoRouting-Dual-Model`: Same as convo-roleplay dual model, but for Open-WebUI.

### Step 3: Go to the [endpoints folder](../../Public/Configs/Endpoints) and find the folder for the user you chose.

### Step 4: Update all the endpoint files.

For single or dual model users this won't be too painful, but for the assistants it's going to suck. Sorry in
advance.

There are a few examples here: [Example Endpoints](../../Public/Configs/Endpoints/_example-endpoints). You can straight
copy the values of those and paste them into the endpoints of the user you want to use, then tweak as needed.

When looking at the file, here is a breakdown of what to change:

* `modelNameForDisplayOnly`- Can ignore that
* `endpoint` - IP Address and port of your LLM API, like you'd normally put in SillyTavern
* `apiTypeConfigFileName` - The name of [one of these files](../../Public/Configs/ApiTypes) in the ApiTypes folder.
  Pick the one that matches your backend. If using Ollama, I recommend `OllamaApiGenerate`. If using Kobold, then
  `KoboldCpp`. `Open-AI-API` is OpenAI chat completions, and `OpenAI-Compatible-Completions` is v1/completions.
* `maxContextTokenSize` - Context size you loaded the model with
* `modelNameToSendToAPI` - If you are using Ollama, this must match the name of the model you loaded. For anything else,
  it doesn't matter.
* `promptTemplate` - The [file name of the Prompt template](../../Public/Configs/PromptTemplates) for the LLM you're
  using. Chances are there's already a template in there for what you need, but you can add more in there if you
  need. They are pretty similar to how SillyTavern does its templates.
* `addGenerationPrompt` - Likely safe to just leave this as true. Almost every model I've used likes this.

### Step 5: Pop over to your [user file](../../Public/Configs/Users) and tweak a few things

There's lots of stuff in here, but for a quick start you don't really need to look at a lot of it.

Here are the important bits for a quick start:

* 'discussionDirectory' - This is where your memories and chat summaries will land. They are written in json files
  so that you can modify them, delete them, etc. This has to be pointed to an actual location
* 'sqlLiteDirectory' - Some utility tasks use a sqlLite db, like workflow locks. This also needs to be a real location,
  and I usually just make it the same directory as above.
* `useOfflineWikiApi` - If you don't plan to get
  the [OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi), set this to false. Otherwise
  if it is true then it will use that for factual workflows on the assistant or routing users.

### Step 6: Start Up Wilmer

You can start Wilmer via the bat or bash file. I always recommend peeking over such files or asking chatgpt
if they are safe before running one.

Both of these files have access
to [a few optional properties](../../README.md#script-arguments-for-bat-sh-and-py-files),
and specifying a user is one of them. So an example would be

`bash run_macos.sh --User "Convo-Roleplay-Single-Model"`

NOTE- If you get an error, there could be a lot of reasons but the most common for me is
accidentally leaving a typo or something in one of the json files. Peek at the error and it
may tell you what file type, and then you can go check if you did.




