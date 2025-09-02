## Quick Guide to Setting up WilmerAI *(Out of Date. Will Update Soon)*

### Step 1: Download Wilmer and unzip it somewhere. Navigate to that folder

### Step 2: [Pick a pre-made user](../../../README.md#step-2-fast-route-use-pre-made-users)

Short version desc of each:

* **\_example\_simple\_router\_no\_memory**: This is a simple user that has routing to WIKI, CODING and GENERAL
  categories, each going to a special workflow. Best used with direct and productive front ends like Open WebUI.
  Requires the Offline Wikipedia API
* **\_example\_general\_workflow**: This is a simple user that runs a single general purpose workflow. Simple, to the
  point. Best used with direct and productive front ends like Open WebUI. Requires the Offline Wikipedia API
* **\_example\_coding\_workflow**: This is a simple user that runs a single coding workflow. Simple, to the point. Best
  used with direct and productive front ends like Open WebUI. Requires the Offline Wikipedia API
* **\_example\_wikipedia\_multi\_step\_workflow**: This is a wikipedia search against the Offline Wikipedia API.
  Requires the Offline Wikipedia API
* **\_example\_wikipedia\_multi\_step\_workflow**: This is a wikipedia search against the Offline Wikipedia API, but
  instead of just 1 pass it does a total of 4, attempting to build up extra info for the report. Still very
  experimental; not sure how I feel about the results yet. Requires the Offline Wikipedia API
* **\_example\_assistant\_with\_vector\_memory**: This template is for a simple "assistant" that will diligently think
  through your message via a series of workflow nodes, and will attempt to track important facts in a simple vector
  memory implementation (*EXPERIMENTAL*)
  > This user thinks a LOT, so it's slow and chews up tokens. I recommend using a non-reasoning model with this. Use
  this with a local model or prepare for it to expensive
* **\_example\_game\_bot\_with\_file\_memory**: This is best used with a game front end, like a custom text game
  implementation or SillyTavern. This is an experimental user with the goal of trying to solve some of the common
  complaints or problems that have voiced on various boards. Feedback is welcome.
  > Again this is expensive and thinks a lot. It's very slow.

### Step 3: Go to the [endpoints folder](../../../Public/Configs/Endpoints) and find the folder for the user you chose.

### Step 4: Update all the endpoint files.

There are a few examples here: [Example Endpoints] (../../../Public/Configs/Endpoints/_example-endpoints). You can
straight
copy the values of those and paste them into the endpoints of the user you want to use, then tweak as needed.

When looking at the file, here is a breakdown of what to change:

* `modelNameForDisplayOnly`- Can ignore that
* `endpoint` - IP Address and port of your LLM API, like you'd normally put in SillyTavern
* `apiTypeConfigFileName` - The name of [one of these files] (../../../Public/Configs/ApiTypes) in the ApiTypes folder.
  Pick the one that matches your backend. If using Ollama, I recommend `OllamaApiGenerate`. If using Kobold, then
  `KoboldCpp`. `Open-AI-API` is OpenAI chat completions, and `OpenAI-Compatible-Completions` is v1/completions.
* `maxContextTokenSize` - Context size you loaded the model with
* `modelNameToSendToAPI` - If you are using Ollama, this must match the name of the model you loaded. For anything else,
  it doesn't matter.
* `promptTemplate` - The [file name of the Prompt template] (../../../Public/Configs/PromptTemplates) for the LLM you're
  using. Chances are there's already a template in there for what you need, but you can add more in there if you
  need. They are pretty similar to how SillyTavern does its templates.
* `addGenerationPrompt` - Likely safe to just leave this as true. Almost every model I've used likes this.

### Step 5: Pop over to your [user file] (../../../Public/Configs/Users) and tweak a few things

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
to [a few optional properties](../../../README.md#script-arguments-for-bat-sh-and-py-files),
and specifying a user is one of them. So an example would be

`bash run_macos.sh --User "_user_general_workflow"`

NOTE- If you get an error, there could be a lot of reasons but the most common for me is
accidentally leaving a typo or something in one of the json files. Peek at the error and it
may tell you what file type, and then you can go check if you did.