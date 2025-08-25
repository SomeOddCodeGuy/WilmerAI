## DISCLAIMER:

> This is a personal project under heavy development. It could, and likely does, contain bugs, incomplete code,
> or other unintended issues. As such, the software is provided as-is, without warranty of any kind.
>
> This project and any expressed views, methodologies, etc., found within are the result of contributions by the
> maintainer and any contributors in their free time, and should not reflect upon any of their employers.

---

## What is WilmerAI?

Wilmer is an application that sits between your front end (or any other LLM-calling program) and the LLM APIs you're
sending your prompts to.

To connect to it, Wilmer exposes OpenAI- and Ollama-compatible API endpoints, and on the backend it can connect to LLM
APIs like OpenAI, KoboldCpp, and Ollama.

To visualize: you type a prompt into your front end, which is connected to Wilmer. The prompt gets sent to Wilmer
first, which runs it through a series of workflows. Each workflow may make calls to multiple LLMs, after which the final
response comes back to you.

From your perspective, it looks like a (likely long-running) one-shot call to an LLM. But in reality, it could involve
many
LLMs—and even tools—performing complex work.

### What Does WilmerAI Stand For?

WilmerAI stands for **"What If Language Models Expertly Routed All Inference?"**

---

## Maintainer's Note — UPDATED 2025-08-17

> **IMPORTANT:**  
> Until October 2025, WilmerAI will not accept any new Pull Requests that modify anything within the
> Middleware modules; some exceptions may apply. Updates to iSevenDays' new MCP tool-calling feature, or adding new
> custom users or prompt templates within the Public directory, are still welcome.
>
> **Roadmap to Complete Before New PRs Accepted**
> * ~~Reasoning LLM Support (think block removal, prepend text to prompt/system)~~ **(COMPLETE)**
> * ~~Refactor LlmApis~~ **(First Round COMPLETE)**
> * ~~Refactor FrontEnd Apis~~ **(First Round COMPLETE)**
> * ~~Refactor Workflows~~ **(First Round COMPLETE)**
> * ~~Vector Memory Initial Implementation~~ **(COMPLETE)**
> * Rewrite Readme and Expand Documentation *(In Progress)*
> * Full Redo of Most Example Users, Using New Prompting Strategies *(In Progress)*
> * Second Round Refactoring for Unit Tests
> * Full Unit Test Coverage of Primary Functions
>
> During this time, there are very likely to be new bugs introduced. I really don’t have the ability
> to work on this project during the week at all, so it’s a heads-down code-a-thon on weekends whenever
> I can. Please bear with me if I break stuff along the way over the next few weeks.
>
> To help reduce the pain of this, I’ve finally set up tags/releases, with major checkpoints from the past
> few months chosen so you can grab earlier, better-working versions.
>
> PS: Please bear with me if one of my documents says something dumb. When time is short, documentation usually
> suffers the most, so I’m relying heavily on LLMs right now. Normally I would do it by hand or at least
> proofread it better—so I apologize in advance. I’ll clean that up soon-ish.
>
> — Socg

## The Power of Workflows

### Semi-Autonomous Workflows Allow You Determine What Tools and When

The below shows Open WebUI connected to 2 instances of Wilmer. The first instance just hits Mistral Small 3 24b
directly, and then the second instance makes a call to
the [Offline Wikipedia API](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi) before making the call to the
same model.

![No-RAG vs RAG](Docs/Gifs/Search-Gif.gif)
*Click the image to play gif if it doesn't start automatically*

### Iterative LLM Calls To Improve Performance

A zero-shot to an LLM may not give great results, but follow-up questions will often improve them. If you
regularly
perform [the same follow-up questions when doing tasks like software development](https://github.com/SomeOddCodeGuy/SomeOddCodeGuy/blob/main/Github_Images/My%20personal%20guide%20for%20developing%20software%20with%20AI%20assistance%20r_LocalLLaMA.png),
creating a workflow to
automate those steps can have great results.

### Distributed LLMs

With workflows, you can have as many LLMs available to work together in a single call as you have computers to support.
For example, if you have old machines lying around that can run 3-8b models? You can put them to use as worker LLMs in
various nodes. The more LLM APIs that you have available to you, either on your own home hardware or via proprietary
APIs, the more powerful you can make your workflow network. A single prompt to Wilmer could reach out to 5+ computers,
including proprietary APIs, depending on how you build your workflow.

## Some (Not So Pretty) Pictures to Help People Visualize What It Can Do

#### Example of A Simple Assistant Workflow Using the Prompt Router

![Single Assistant Routing to Multiple LLMs](Docs/Examples/Images/Wilmer-Assistant-Workflow-Example.jpg)

#### Example of How Routing Might Be Used

![Prompt Routing Example](Docs/Examples/Images/Wilmer-Categorization-Workflow-Example.png)

#### Group Chat to Different LLMs

![Groupchat to Different LLMs](Docs/Examples/Images/Wilmer-Groupchat-Workflow-Example.png)

#### Example of a UX Workflow Where A User Asks for a Website

![Oversimplified Example Coding Workflow](Docs/Examples/Images/Wilmer-Simple-Coding-Workflow-Example.jpg)

## Key Features

- **Prompt Routing**: Prompts sent into Wilmer can be routed to any custom category, whether that be a domain (like
  coding, math, medical, etc) or a persona name (for groups chats with a different LLM for each persona).


- **Custom Workflows**: Routing isn't required; you can also override the routing so that every prompt goes to a single
  workflow every time.


- **Single Prompts Responded To By Multiple LLMs in tandem**: Every node in a workflow can hit a different LLM if you
  want, so a single prompt could be worked on by 10+ LLMs if that was what you wanted. This means one AI assistant can
  be powered by several workflows, and many LLMs, all working together to generate the best answer.


- **Support For The Offline Wikipedia API**: WilmerAI has a node that can make calls to the
  [OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi), to allow for RAG setups to
  improve factual responses.


- **Continually Generated Chat Summaries to Simulate a "Memory"**: The Chat Summary node will generate "memories",
  by chunking your messages and then summarizing them and saving them to a file. It will then take those summarized
  chunks and generate an ongoing, constantly updating, summary of the entire conversation. This allows conversations
  that far exceed the LLM's context to continue to maintain some level of consistency.


- **Hotswap Models to Maximize VRAM Usage:** Leveraging Ollama's hotswapping, you can run complex workflows even on
  systems with smaller amounts of VRAM. For example, if a 24GB RTX 3090 can load a 14b model, then using endpoints
  pointed towards Ollama, you can have workflows with as many 14b models as your computer has storage to hold, and
  each node that uses a different model will cause Ollama to unload the previous model, and load the new one.


- **Customizable Presets**: Presets are saved in a json file that you can readily customize. Presets are configured in
  json files and sent as-is to the API, so if a new sampler comes out that isn't included in Wilmer, you can just
  pop into the json file for the preset and update it. Each LLM type that Wilmer hits gets its own preset folder.


- **Vision Multi-Modal Support Via Ollama:** Experimental support of image processing when using
  Ollama as the front end API, and having an Ollama backend API to send it to. Send multiple images in a single
  message, even if the LLM itself does not support that; Wilmer will iterate through them and query the LLM
  one at a time. The images can either be utilized as variables for prompts in other workflows, or can be added
  to the conversation as messages.


- **Mid-Workflow Conditional Workflows:** Similar to the main domain routing, you can kick off new workflows inside
  of other workflows, either directly or based on a condition. So you can ask the LLM "Would a Wikipedia article help
  here?", and if the answer is 'yes' then kick off a wikipedia workflow, or if 'no' then kick off a workflow that just
  hits LLMs.


- **MCP Server Tool Integration using MCPO:** New and experimental support for MCP
  server tool calling using MCPO, allowing tool use mid-workflow. Big thank you
  to [iSevenDays](https://github.com/iSevenDays)
  for the amazing work on this feature. More info can be found in the [ReadMe](Public/modules/README_MCP_TOOLS.md)

## Why Make WilmerAI?

Wilmer was kicked off in late 2023, during the Llama 2 era, to make maximum use of fine-tunes through routing.
The routers that existed at the time didn't handle semantic routing well- often categorizing was based on a single
word and the last message only; but sometimes a single word isn't enough to describe a category, and the last
message may have too much inferred speech or lack too much context to appropriately categorize on.

Almost immediately after Wilmer was started, it became apparent that just routing wasn't enough: the finetunes were ok,
but nowhere near as smart as proprietary LLMs. However, when the LLMs were forced to iterate on the same task over and
over, the quality of their responses tended to improve (as long as the prompt was well written). This meant that the
optimal result wasn't routing just to have a single LLM one-shot the response, but rather sending the prompt to
something
more complex.

Instead of relying on unreliable autonomous agents, Wilmer became focused on semi-autonomous Workflows, giving the
user granular control of the path the LLMs take, and allow maximum use of the user's own domain knowledge and
experience. This also meant that multiple LLMs could work together, orchestrated by the workflow itself,
to come up with a single solution.

Rather than routing to a single LLM, Wilmer routes to many via a whole workflow.

This has allowed Wilmer's categorization to be far more complex and customizable than most routers. Categorization is
handled by user defined workflows, with as many nodes and LLMs involved as the user wants, to break down the
conversation and determine exactly what the user is asking for. This means the user can experiment with different
prompting styles to try to make the router get the best result. Additionally, the routes are more than just keywords,
but rather full descriptions of what the route entails. Little is left to the LLM's "imagination". The goal is that
any weakness in Wilmer's categorization can be corrected by simply modifying the categorization workflow. And once
that category is chosen? It goes to another workflow.

Eventually Wilmer became more about Workflows than routing, and an optional bypass was made to skip routing entirely.
Because of the small footprint, this means that users can run multiple instances of Wilmer- some hitting a workflow
directly, while others use categorization and routing.

While Wilmer may have been the first of its kind, many other semantic routers have since appeared; some of which are
likely faster and better. But this project will continue to be maintained for a long time to come, as the maintainer
of the project still uses it as his daily driver, and has many more plans for it.

## Wilmer API Endpoints

### How Do You Connect To Wilmer?

Wilmer exposes several different APIs on the front end, allowing you to connect most applications in the LLM space
to it.

Wilmer exposes the following APIs that other apps can connect to it with:

- OpenAI Compatible v1/completions (*requires [Wilmer Prompt Template](Public/Configs/PromptTemplates/wilmerai.json)*)
- OpenAI Compatible chat/completions
- Ollama Compatible api/generate (*requires [Wilmer Prompt Template](Public/Configs/PromptTemplates/wilmerai.json)*)
- Ollama Compatible api/chat

### What Wilmer Can Connect To

On the backend, Wilmer is capable to connecting to various APIs, where it will send its prompts to LLMs. Wilmer
currently is capable of connecting to the following API types:

- OpenAI Compatible v1/completions
- OpenAI Compatible chat/completions
- Ollama Compatible api/generate
- Ollama Compatible api/chat
- KoboldCpp Compatible api/v1/generate (*non-streaming generate*)
- KoboldCpp Compatible /api/extra/generate/stream (*streaming generate*)

Wilmer supports both streaming and non-streaming connections, and has been tested using both Sillytavern
and Open WebUI.

## Maintainer's Note:

> This is a passion project that is being supported in my free time. I do not have the ability to contribute to this
> during standard business hours on
> weekdays due to work, so my only times to make code updates are weekends, and some weekday late nights.
>
> If you find a bug or other issue, a fix may take a week or two to go out. I apologize in
> advance if that ends up being the case, but please don't take it as meaning I am not taking the
> issue seriously. In reality, I likely
> won't have the ability to even look at the issue until the following Friday or Saturday.
>
> -Socg

## IMPORTANT:

> Please keep in mind that workflows, by their very nature, could make many calls to an API endpoint based on how you
> set them up. WilmerAI does not track token usage, does not report accurate token usage via its API, nor offer any
> viable
> way to monitor token usage. So if token usage tracking is important to you for cost reasons, please be sure to keep
> track of how many tokens you are using via any dashboard provided to you by your LLM APIs, especially early on as you
> get used to this software.
>
>Your LLM directly affects the quality of WilmerAI. This is an LLM driven project, where the flows and outputs are
> almost
> entirely dependent on the connected LLMs and their responses. If you connect Wilmer to a model that produces lower
> quality outputs, or if your presets or prompt template have flaws, then Wilmer's overall quality will be much lower
> quality as well. It's not much different than agentic workflows in that way.

### Youtube Videos

[WilmerAI Setup Tutorial](https://www.youtube.com/watch?v=v2xYQCHZwJM)

This 40 minute video shows:

- A walkthrough of downloading and setting up Wilmer
- Running Wilmer and sending a cURL command to it
- A walkthrough of the wikipedia workflow
- A brief talk of the new Socg users

[WilmerAI Tutorial Youtube PlayList](https://www.youtube.com/playlist?list=PLjIfeYFu5Pl7J7KGJqVmHM4HU56nByb4X)

This 3 hour video series shows:

- A more in-depth walkthrough of Wilmer and what it is
- An explanation of some of the workflows, as well as the custom python script module
- Explaining Socg's personal setup
- Setting up and running an example user
- Showing a run of a workflow on an RTX 4090 that utilizes Ollama's ability to hotswap multiple 14b models,
  allowing a 24GB video card to run as many models that would fit individually on the card as you have hard
  drive space for.

### Connecting in SillyTavern

#### Text Completion

To connect as a Text Completion in SillyTavern, follow these steps (the below screenshot is from SillyTavern):

Connect as OpenAI Compatible v1/Completions:

![OpenAI Text Completion Settings](Docs/Examples/Images/ST_text_completion_settings.png)

OR

Connect as Ollama api/generate:

![Ollama Text Completion Settings](Docs/Examples/Images/ST_ollama_text_completion_settings.png)

When using text completions, you need to use a WilmerAI-specific Prompt Template format. An importable ST file can be
found within `Docs/SillyTavern/InstructTemplate`. The context template is also included if you'd like to use that as
well.

The instruction template looks like this:

```
[Beg_Sys]You are an intelligent AI Assistant.[Beg_User]SomeOddCodeGuy: Hey there![Beg_Assistant]Wilmer: Hello![Beg_User]SomeOddCodeGuy: This is a test[Beg_Assistant]Wilmer:  Nice.
```

From SillyTavern:

```
    "input_sequence": "[Beg_User]",
    "output_sequence": "[Beg_Assistant]",
    "first_output_sequence": "[Beg_Assistant]",
    "last_output_sequence": "",
    "system_sequence_prefix": "[Beg_Sys]",
    "system_sequence_suffix": "",
```

There are no expected newlines or characters between tags.

Please ensure that Context Template is "Enabled" (checkbox above the dropdown)

#### Chat Completions (Not Recommended)

To connect as Open AI Chat Completions in SillyTavern, follow these steps (the below screenshot is from SillyTavern):

![Chat Completion Settings](Docs/Examples/Images/ST_chat_completion_settings.png)

* Once connected, your presets are largely irrelevant and will be controlled by Wilmer; settings like temperature,
  top_k, etc. The only field you need to update is your truncate length. I recommend setting it to the maximum your
  front end will allow; in SillyTavern, that is around 200,000 tokens.
* If you connect via chat/Completion, please go to presets, expand "Character Names Behavior", and set it to "Message
  Content". If you do not do this, then go to your Wilmer user file and set `chatCompleteAddUserAssistant` to true. (I
  don't recommend setting both to true at the same time. Do either character names from SillyTavern, OR user/assistant
  from Wilmer. The AI might get confused otherwise.)

### Additional Recommendations

For either connection type, I recommend going to the "A" icon in SillyTavern and selecting "Include Names" and "Force
Groups and Personas" under instruct mode, and then going to the far left icon (where the samplers are) and checking
"stream" on the top left, and then on the top right checking "unlock" under context and dragging it to 200,000+. Let
Wilmer
worry about the context.

### Connecting in Open WebUI

When connecting to Wilmer from Open WebUI, simply connect to it as if it were an Ollama instance.

![Ollama Open WebUI Settings](Docs/Examples/Images/OW_ollama_settings.png)

## Quick-ish Setup

Wilmer currently has no user interface; everything is controlled via JSON configuration files located in the "Public"
folder. This folder contains all essential configurations. When updating or downloading a new copy of WilmerAI, you
should
simply copy your "Public" folder to the new installation to retain your settings.

This section will walk you through setting up Wilmer. I have broken the sections into steps; I might recommend copying
each step, 1 by 1, into an LLM and asking it to help you set the section up. That may make this go much easier.

**IMPORTANT NOTES**
> It is important to note three things about Wilmer setup.
> * A) Preset files are 100% customizable. What is in that file goes to the llm API. This is because cloud
    APIs do not handle some of the various presets that local LLM APIs handle. As such, if you use OpenAI API
    or other cloud services, the calls will probably fail if you use one of the regular local AI presets. Please
    see the preset "OpenAI-API" for an example of what openAI accepts.
>
>
> * B) I have recently replaced all prompts in Wilmer to go from using the second person to third person. This has
    had pretty decent results for me, and I'm hoping it will for you as well.
>
>
> * C) By default, all the user files are set to turn on streaming responses. You either need to enable
    this in your front end that is calling Wilmer so that both match, or you need to go into Users/username.json
    and set Stream to "false". If you have a mismatch, where the front end does/does not expect streaming and your
    wilmer expects the opposite, nothing will likely show on the front end.

### Step 1: Installing the Program

Installing Wilmer is straightforward. Ensure you have Python installed; the author has been using the program with
Python 3.10 and 3.12, and both work well.

**Option 1: Using Provided Scripts**

For convenience, Wilmer includes a BAT file for Windows and a .sh file for macOS. These scripts will create a virtual
environment, install the required packages from `requirements.txt`, and then run Wilmer. You can use these scripts to
start Wilmer each time.

- **Windows**: Run the provided `.bat` file.
- **macOS**: Run the provided `.sh` file.
- **linux**: The author doesn't have a Linux machine and can't test it, so none is provided

> **IMPORTANT:** Never run a BAT or SH file without inspecting it first, as this can be risky. If you are unsure about
> the safety of such a file, open it in Notepad/TextEdit, copy the contents and then ask your LLM to review it for any
> potential issues.

**Option 2: Manual Installation**

Alternatively, you can manually install the dependencies and run Wilmer with the following steps:

1. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

2. Start the program:
   ```bash
   python server.py
   ```

The provided scripts are designed to streamline the process by setting up a virtual environment. However, you can safely
ignore them if you prefer manual installation.

#### Script arguments for .bat, .sh and .py files:

**NOTE**: When running either the bat file, the sh file or the python file, all three now accept the following
OPTIONAL arguments:

* "--ConfigDirectory": Directory where your config files can be found. By default, this is the "Public" folder within
  the Wilmer root.
* "--LoggingDirectory": The directory where file logs, if enabled, are stored. Be default file logging is turned OFF,
  and in the event that they are enabled in the user json, they default to going to the "logs" folder in the Wilmer root
* "--User": The user that you want to run under.

So, for example, consider the following possible runs:

* `bash run_macos.sh` (will use user specified in _current-user.json, configs in "Public", logs in "logs")
* `bash run_macos.sh --User "single-model-assistant"` (will default to public for configs and "log" for logs)
* `bash run_macos.sh --ConfigDirectory "/users/socg/Public/configs" --User "single-model-assistant"` (will just
  use default for "logs"
* `bash run_macos.sh --ConfigDirectory "/users/socg/Public/configs" --User "single-model-assistant" --LoggingDirectory
  "/users/socg/wilmerlogs"`

This these optional arguments allow users to spin up multiple instances of WilmerAI, each instance using a different
user profile, logging to a different place, and specifying configs at a different location, if desired.

### Step 2 Fast Route: Use Pre-made Users

Within the Public/Configs you will find a series of folders containing json files. The two that you are
most interested in are the `Endpoints` folder and the `Users` folder.

**NOTE:** The Factual workflow nodes of the `assistant-single-model`, `assistant-multi-model`
and `group-chat-example` users will attempt to utilize the
[OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi)
project to pull full wikipedia articles to RAG against. If you don't have this API, the workflow
should not have any issues, but I personally use this API to help improve the factual responses I get.
You can specify the IP address to your API in the user json of your choice.

First, choose which template user you'd like to use:

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

**IMPORTANT**: Each of the above users call custom workflows pointing to workflows in the _common directory. You can
find other workflows to swap out as well.

Once you have selected the user that you want to use, there are a couple of steps to perform:

1) Update the endpoints for your user under Public/Configs/Endpoints. The example characters are sorted into folders
   for each. The user's endpoint folder is specified at the bottom of their user.json file. You will want to fill in
   every endpoint
   appropriately for the LLMs you are using. You can find some example endpoints under the `_example-endpoints` folder.
    1) **NOTE** Currently, there is best support for standard openai chat completions and v1 completions endpoints, and
       recently KoboldCpp's generate endpoint was added to the mix, since that is the author's favorite to use. If you
       use
       koboldcpp, I HIGHLY recommend turning off context shifting (--noshift). It will absolutely break Wilmer.

2) You will need to set your current user. You can do this when running the bat/sh/py file by using the --User argument,
   or you can do this in Public/Configs/Users/_current-user.json.
   Simply put the name of the user as the current user and save.

3) You will want to open your user json file and peek at the options. Here you can set whether you want streaming or
   not,
   can set the IP address to your offline wiki API (if you're using it), specify where you want your memories/summary
   files
   to go during DiscussionId flows, and also specify where you want the sqllite db to go if you use Workflow Locks.

That's it! Run Wilmer, connect to it, and you should be good to go.

### Step 2 Slow Route: Endpoints and Models (Learn How to Actually Use the Thing)

First, we'll set up the endpoints and models. Within the Public/Configs folder you should see the following sub-folders.
Let's
walk
through what you need.

### **Endpoints**

These configuration files represent the LLM API endpoints you are connected to. For example, the following JSON file,
`SmallModelEndpoint.json`, defines an endpoint:

```json
{
  "modelNameForDisplayOnly": "Small model for all tasks",
  "endpoint": "http://12.0.0.1:5000",
  "apiTypeConfigFileName": "KoboldCpp",
  "maxContextTokenSize": 8192,
  "modelNameToSendToAPI": "",
  "trimBeginningAndEndLineBreaks": true,
  "dontIncludeModel": false,
  "removeThinking": true,
  "startThinkTag": "<think>",
  "endThinkTag": "</think>",
  "openingTagGracePeriod": 100,
  "expectOnlyClosingThinkTag": false,
  "addTextToStartOfSystem": true,
  "textToAddToStartOfSystem": "/no_think ",
  "addTextToStartOfPrompt": false,
  "textToAddToStartOfPrompt": "",
  "addTextToStartOfCompletion": false,
  "textToAddToStartOfCompletion": "",
  "ensureTextAddedToAssistantWhenChatCompletion": false,
  "removeCustomTextFromResponseStartEndpointWide": false,
  "responseStartTextToRemoveEndpointWide": []
}
```

- **endpoint**: The address of the LLM API that you are connecting to. Must be an OpenAI-compatible API of either text
  Completions or Chat Completions type (if you're unsure—that's the vast majority of APIs, so this will probably work
  with whatever you're trying).
- **apiTypeConfigFileName**: The exact name of the JSON file from the `ApiTypes` folder that specifies what type of API
  this is, minus the ".json" extension. "Open-AI-API" will probably work for most cloud services.
- **maxContextTokenSize**: Specifies the max token size that your endpoint can accept. This is used to set the model's
  truncation length property.
- **modelNameToSendToAPI**: Specifies what model name to send to the API. For cloud services, this can be important. For
  example, OpenAI may expect "gpt-3.5-turbo" here. For local AI running in Kobold, text-generation-webui, etc., this is
  mostly unused. (Ollama may use it, though).
- **trimBeginningAndEndLineBreaks**: This boolean will run a trim at the start and end of the final response to remove
  any spaces or linebreaks before or after the text. Some LLMs don't handle those extra spaces/lines well.
- **dontIncludeModel**: This will NOT send the model name you specify in your endpoint config to the LLM API endpoint.
  Generally, sending that model name will tell systems like MLX, Llama.cpp server, and Ollama to load the model with
  that name. You may have a reason why you don't want it to do that and instead have the model you already loaded on
  that port be used. Setting this to `true` will stop the model name from being sent.
- **removeThinking**: This boolean is for reasoning models. By setting this to `true`, it will completely strip out the
  thinking text from responses coming from LLMs, both for streaming and non-streaming. (NOTE: When streaming, this
  buffers the response until thinking is done. That means it looks like the LLM isn't sending you anything, but in
  actuality, it's thinking. The moment the thinking is done, this will remove the thinking block and start sending you
  the LLM's response. So as a user, it just looks like the time to first token is far longer than it is.)
- **startThinkTag** & **endThinkTag**: Allows you to set custom think tags. Some LLMs do things like `<reasoning>` or
  `<thinking>` as opposed to `<think>`. With these, each endpoint can account for the specific start and end tags it
  expects. Both must be defined for `removeThinking` to work.
- **openingTagGracePeriod**: An integer defining the number of characters at the beginning of the LLM's response to scan
  for a `startThinkTag`. If the tag is not found within this window, the system assumes there is no thinking block and
  disables removal for the rest of the response.
- **expectOnlyClosingThinkTag**: This is for models that sometimes don't send their opening think tag and instead just
  start thinking. This will continue to buffer the response until the `endThinkTag` appears, at which point it removes
  everything before that and sends the rest of the stream. If no closing tag appears, you may get a dump of the whole
  response at once.
- **addTextToStartOfSystem**: This will add whatever text you put in `textToAddToStartOfSystem` to the start of the
  system prompt. Made specifically for models that accept commands like "/no\_think ". This will make every prompt run
  by this specific endpoint add that text.
- **textToAddToStartOfSystem**: The text to add if `addTextToStartOfSystem` is `true`.
- **addTextToStartOfPrompt**: Same as the one for system, but this adds it to the beginning of the last user message in
  a chat history, or the beginning of the whole user prompt in a `v1/Completion` context.
- **textToAddToStartOfPrompt**: The text to add if `addTextToStartOfPrompt` is `true`.
- **addTextToStartOfCompletion**: This is meant to seed the start of the AI's response. The intention was for reasoning
  models, so that you can forcefully add opening and closing think tags. However, you can also use it to force the LLM
  to respond in certain ways, like the old trick of having the LLM always start with "Absolutely\! Here is your
  answer: ".
- **textToAddToStartOfCompletion**: The text to add if `addTextToStartOfCompletion` is `true`.
- **ensureTextAddedToAssistantWhenChatCompletion**: If `addTextToStartOfCompletion` is enabled for a Chat Completions
  model, this setting will ensure the text is added inside a new assistant message if the conversation does not already
  end with one. Some inference APIs may not appreciate this.
- **removeCustomTextFromResponseStartEndpointWide**: A boolean that, if `true`, enables the removal of custom
  boilerplate text from the beginning of an LLM's response.
- **responseStartTextToRemoveEndpointWide**: A list of strings to check for and remove from the start of the LLM's
  response if `removeCustomTextFromResponseStartEndpointWide` is `true`. For example,
  `["Assistant:", "Okay, here's the answer:"]`. The system will remove the first match it finds.

##### Amusing Example of Completion Seeding

As a final quick test of addTextToStartOfCompletion before getting this commit ready, I ran the below test having my
workflow describe a picture of a cat that I sent it. The response amused me.

```json
  "addTextToStartOfCompletion": true,
"textToAddToStartOfCompletion": "Roses are red, violets are blue,  ",
"ensureTextAddedToAssistantWhenChatCompletion": true
```

![Completion Seeding: Roses Are Red...](Docs/Examples/Images/Completion_Seed_Roses_Red.png)

#### ApiTypes

These configuration files represent the different API types that you might be hitting when using Wilmer.

```json
{
  "nameForDisplayOnly": "KoboldCpp Example",
  "type": "koboldCppGenerate",
  "presetType": "KoboldCpp",
  "truncateLengthPropertyName": "max_context_length",
  "maxNewTokensPropertyName": "max_length",
  "streamPropertyName": "stream"
}
```

- **type**: Can be either: `KoboldCpp`, `OllamaApiChat`, `OllamaApiChatImageSpecific`, `OllamaApiGenerate`,
  `Open-AI-API`, `OpenAI-Compatible-Completions`, or `Text-Generation-WebUI`.
- **presetType**: This specifies the name of the folder that houses the presets you want to use. If you peek in the
  Presets
  folder, you'll see what I mean. Kobold has the best support. I plan to add more support for others later. With that
  said, there is absolutely nothing stopping you from making a new folder in Presets, putting your own json in with
  whatever
  your favorite LLM program accepts with the payload, making a new API type json, and using it. Very little about
  presets are hardcoded. I suspect that when I try to add proper support for Ollama and text-generation-webui, I may not
  need
  any code changes at all; just some new jsons/folders.
- **truncateLengthPropertyName**: This specifies what the API expects the max context size field to be called
  when sending a request. Compare the Open-AI-API file to the KoboldCpp file; Open-AI-API doesn't support this
  field at all, so we left it blank. Whereas KoboldCpp does support it, and it expects us to send the value
  with the property name "truncation_length". If you are unsure what to do, for locally running APIs I recommend
  trying KoboldCpp's settings, and for cloud I recommend trying Open-AI-API's settings. The actual value we send
  here is in the Endpoints config.
- **maxNewTokensPropertyName**: Similar to the truncate length, this is the API's expected property name
  for the number of tokens you want the LLM to respond with. The actual value we send here is on each individual
  node within workflows.
- **streamPropertyName**: Same as max tokens and truncate length. This specifies the field name for whether to
  stream the response to the front end or send the whole response as a text block once it is done.

#### PromptTemplates

These files specify the prompt template for a model. Consider the following example, `llama3.json`:

```json
{
  "promptTemplateAssistantPrefix": "<|start_header_id|>assistant<|end_header_id|>\n\n",
  "promptTemplateAssistantSuffix": "<|eot_id|>",
  "promptTemplateEndToken": "",
  "promptTemplateSystemPrefix": "<|start_header_id|>system<|end_header_id|>\n\n",
  "promptTemplateSystemSuffix": "<|eot_id|>",
  "promptTemplateUserPrefix": "<|start_header_id|>user<|end_header_id|>\n\n",
  "promptTemplateUserSuffix": "<|eot_id|>"
}
```

These templates are applied to all v1/Completion endpoint calls. If you prefer not to use a template, there is a file
called `_chatonly.json` that breaks up messages with newlines only.

### Step 3: Creating a User

Creating and activating a user involves four major steps. Follow the instructions below to set up a new user.

#### Users Folder

First, within the `Users` folder, create a JSON file for the new user. The easiest way to do this is to copy an existing
user JSON file, paste it as a duplicate, and then rename it. Here is an example of a user JSON file:

```json
{
  "port": 5006,
  "stream": true,
  "customWorkflowOverride": false,
  "customWorkflow": "CodingWorkflow-LargeModel-Centric",
  "routingConfig": "assistantSingleModelCategoriesConfig",
  "categorizationWorkflow": "CustomCategorizationWorkflow",
  "defaultParallelProcessWorkflow": "SlowButQualityRagParallelProcessor",
  "fileMemoryToolWorkflow": "MemoryFileToolWorkflow",
  "chatSummaryToolWorkflow": "GetChatSummaryToolWorkflow",
  "conversationMemoryToolWorkflow": "CustomConversationMemoryToolWorkflow",
  "recentMemoryToolWorkflow": "RecentMemoryToolWorkflow",
  "discussionIdMemoryFileWorkflowSettings": "_DiscussionId-MemoryFile-Workflow-Settings",
  "discussionDirectory": "D:\\Temp",
  "sqlLiteDirectory": "D:\\Temp",
  "chatPromptTemplateName": "_chatonly",
  "verboseLogging": true,
  "chatCompleteAddUserAssistant": true,
  "chatCompletionAddMissingAssistantGenerator": true,
  "useOfflineWikiApi": true,
  "offlineWikiApiHost": "127.0.0.1",
  "offlineWikiApiPort": 5728,
  "endpointConfigsSubDirectory": "assistant-single-model",
  "presetConfigsSubDirectoryOverride": "preset-folder-that-is-not-username",
  "useFileLogging": false
}
```

- **port**: Specifies the port Wilmer should run on. Choose a port that is not in use. By default, Wilmer hosts
  on `0.0.0.0`, making it visible on your network if run on another computer. Running multiple instances of Wilmer on
  different ports is supported.
- **stream**: Determines whether to stream the output of the LLM to the UI. This setting must match between Wilmer and
  the front end.
- **customWorkflowOverride**: When `true`, the router is disabled, and all prompts go only to the specified workflow,
  making it a single workflow instance of Wilmer.
- **customWorkflow**: The custom workflow to use when `customWorkflowOverride` is `true`.
- **routingConfig**: The name of a routing config file from the `Routing` folder, without the `.json` extension.
- **categorizationWorkflow**: Specifies the workflow used to categorize your prompt. Review and adjust this workflow to
  improve categorization results.
- **defaultParallelProcessWorkflow**: The workflow for parallel processing tasks. If you copy another user folder to
  make yours, you can likely just leave this alone for now, other than changing the endpoints.
- **fileMemoryToolWorkflow**: The workflow for file memory tools. If you copy another user folder to make yours, you can
  likely just leave this alone for now, other than changing the endpoints.
- **chatSummaryToolWorkflow**: The workflow for chat summary tools. If you copy another user folder to make yours, you
  can likely just leave this alone for now, other than changing the endpoints.
- **conversationMemoryToolWorkflow**: The workflow for conversation memory tools. If you copy another user folder to
  make yours, you can likely just leave this alone for now, other than changing the endpoints.
- **recentMemoryToolWorkflow**: The workflow for recent memory tools. If you copy another user folder to make yours, you
  can likely just leave this alone for now, other than changing the endpoints.
- **discussionIdMemoryFileWorkflowSettings**: Settings for the memory file, including memory chunk size and summary
  prompts.
- **discussionDirectory**: Specifies where discussion files are stored. Ensure this directory exists to avoid crashes
  when using `DiscussionId`.
- **sqlLiteDirectory**: Specifies where the sql lite db will be created if you are using workflow locks.
- **chatPromptTemplateName**: Specifies the chat prompt template.
- **verboseLogging**: Currently unused but reserved for future use.
- **chatCompleteAddUserAssistant**: When Wilmer is connected to as a chat/Completions endpoint, sometimes the front end
  won't include names in the messages. This can cause issues for Wilmer. This setting adds "User:" and "Assistant:" to
  messages for better context understanding in that situation.
- **chatCompletionAddMissingAssistantGenerator**: Creates an empty "Assistant:" message as the last message, sort of
  like a prompt generator, when being connected to as chat/Completions endpoint. This is only used
  if `chatCompleteAddUserAssistant` is `true`.
- **useOfflineWikiApi**: This specifies whether you want to use
  the [OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi) for factual workflows
  or for the example group's `DataFinder` character.
- **offlineWikiApiHost**: IP of the computer running the OfflineWikipediaTextApi.
- **offlineWikiApiPort**: Port for your wiki API. Unless you specifically change this, it's already good in all the
  example user configs.
- **endpointConfigsSubDirectory**: Name of the subfolder in Endpoints where your endpoint jsons will live.
- **presetConfigsSubDirectoryOverride**: This is an optional field to specify a different preset sub-directory folder
  name
  than default. The default preset subdirectory folder name will be your username. For backwards compatibility, if it
  cannot find the preset in your username or whatever custom foldername you give, it will look in the root of the api
  type you are using, as that's where presets use to live.
- **useFileLogging**: Specifies whether to log the outputs from Wilmer to a file. By default this is false, and if the
  value does not exist in the config it is false. When false, the logs will be printed to the console. NOTE: The
  optional argument --LoggingDirectory for the .bat, .sh or .py files allow you to override where the logs are written.
  By default they go to the root WilmerAI/logs directory.

#### Users Folder, _current-user.json File

Next, update the `_current-user.json` file to specify what user you want to use. Match the name of the new user JSON
file,
without the `.json` extension.

**NOTE**: You can ignore this if you want to use the --User argument when running Wilmer instead.

#### Routing Folder

Create a routing JSON file in the `Routing` folder. This file can be named anything you want. Update the `routingConfig`
property in your user JSON file with this name, minus the `.json` extension. Here is an example of a routing config
file:

```json
{
  "CODING": {
    "description": "Any request which requires a code snippet as a response",
    "workflow": "CodingWorkflow"
  },
  "FACTUAL": {
    "description": "Requests that require factual information or data",
    "workflow": "ConversationalWorkflow"
  },
  "CONVERSATIONAL": {
    "description": "Casual conversation or non-specific inquiries",
    "workflow": "FactualWorkflow"
  }
}
```

- **Element Name**: The category, such as "CODING", "FACTUAL", or "CONVERSATIONAL".
- **description**: Sent to the categorizing LLM along with the category name to help with prompt categorization.
- **workflow**: The name of the workflow JSON file, without the `.json` extension, triggered if the category is chosen.

#### Workflow Folder

In the `Workflow` folder, create a new folder that matches the username from the `Users` folder. The quickest way to do
this is to copy an existing user's folder, duplicate it, and rename it.

If you choose to make no other changes, you will need to go through the workflows and update the endpoints to point to
the endpoint you want. If you are using an example workflow added with Wilmer, then you should already be fine here.

## Quick Setup RECAP:

Within the "Public" folder you should have:

* You should have created/edited an endpoint to point to your LLM and set up your model
* You should have made a json file with your username in Users folder
* You should have updated _current-user with your new username, or an existing one if you are using a pre-included user
* You should have made a routing json file with your categories in the Routing folder, or chosen the one you want to use
  that is pre-existing
* You should have ensured your new user json file has the correct routing config specified
* You should have a folder with your user's name in the Workflows folder
    * This folder should contain a json matching every workflow from your user folder
    * This folder should contain a json matching every workflow from your Routing config
        * If you're missing a workflow, Wilmer will crash.

## Understanding Workflows

### Setting up Workflows

Workflows in this project are modified and controlled in the `Public/Workflows` folder, within your user's specific
workflows folder. For example, if your user is named `socg` and you have a `socg.json` file in the `Users` folder, then
within workflows you should have a `Workflows/socg` folder.

### Workflow Structure

Workflows are JSON files made up of "nodes" that execute sequentially. The system has been updated to support a more
powerful dictionary-based format that allows for top-level configuration and variables, making workflows much cleaner
and easier to manage.

#### New Format (Recommended)

This format allows you to define custom variables at the top level of the JSON. These variables can then be used in any
node throughout the workflow.

```json
{
  "persona": "You are a helpful and creative AI assistant.",
  "shared_endpoint": "OpenWebUI-NoRouting-Single-Model-Endpoint",
  "nodes": [
    {
      "title": "Gather Relevant Memories",
      "type": "VectorMemorySearch",
      "endpointName": "{shared_endpoint}"
    },
    {
      "title": "Respond to User",
      "type": "Standard",
      "systemPrompt": "{persona}\n\nHere are some relevant memories from our past conversations:\n[\n{agent1Output}\n]",
      "endpointName": "{shared_endpoint}",
      "preset": "Conversational_Preset",
      "returnToUser": true
    }
  ]
}
```

#### Old Format (Still Supported)

For 100% backward compatibility, the original format, which is just a list of nodes, is still fully supported and will
work without any changes.

```json
[
  {
    "title": "Coding Agent",
    "systemPrompt": "You are an exceptionally powerful and intelligent technical AI...",
    "prompt": "",
    "lastMessagesToSendInsteadOfPrompt": 6,
    "endpointName": "SocgMacStudioPort5002",
    "preset": "Coding"
  },
  {
    "title": "Reviewing Agent",
    "systemPrompt": "You are an exceptionally powerful and intelligent technical AI...",
    "prompt": "Please critically review the response: {agent1Output}",
    "endpointName": "SocgMacStudioPort5002",
    "preset": "Coding"
  }
]
```

### Node Properties

A workflow is made up of one or more nodes. Each node is a JSON object with properties that define its behavior.

- **`type`**: **(Required)** A string that determines the node's function. This is the most important property. Common
  types include `"Standard"` (for LLM calls), `"PythonModule"` (for running custom scripts), `"VectorMemorySearch"`, and
  `"CustomWorkflow"` (for running another workflow).
- **`title`**: A descriptive name for the node. This is for your use only and may show up in console logs to help with
  debugging.
- **`systemPrompt`**: The system prompt to send to the LLM API.
- **`prompt`**: The user prompt to send. If left blank, the conversation history will be sent instead, based on the
  `lastMessagesToSendInsteadOfPrompt` value.
- **`lastMessagesToSendInsteadOfPrompt`**: Specify how many recent messages to send to the LLM if the `prompt` field is
  an empty string.
- **`endpointName`**: The name of the LLM API endpoint to use for this node. This must match a JSON file name from the
  `Endpoints` folder (without the `.json` extension).
- **`preset`**: The preset to use for the API call, controlling parameters like temperature and token limits. This must
  match a JSON file name from the `Presets` folder (without the `.json` extension).
- **`maxResponseSizeInTokens`**: Overrides the preset to specify the maximum number of tokens for the LLM's response for
  this specific node.
- **`addUserTurnTemplate`**: A boolean. Set to `false` if you are sending raw conversation history. Set to `true` if you
  are sending a custom string via the `prompt` field that should be wrapped in the user turn template.
- **`returnToUser`**: A boolean. If set to `true` on a node that is not the final one, its output will be returned to
  the user immediately. This is useful for "fire and forget" tasks where later nodes perform background actions (like
  saving memories) without making the user wait.
- **`useRelativeTimestamps`**: A boolean. If set to `true`, timestamps will be prepended to messages in a
  human-readable, relative format (e.g., `[Sent 5 minutes ago]`). If omitted or `false`, absolute timestamps are used.
- **`workflowName`**: Used only in `"CustomWorkflow"` nodes. Specifies the file name of the sub-workflow to execute.
- **`scoped_variables`**: Used only in `"CustomWorkflow"` nodes. A list of variables from the current workflow (e.g.,
  `["{agent1Output}"]`) to pass into the sub-workflow. These become available as `{agent#Input}` variables inside the
  sub-workflow.

### Variables in Prompts

You can use a rich set of dynamic variables within `systemPrompt` and `prompt` fields. These placeholders will be
replaced with real-time values when the workflow runs.

#### Inter-Node & Workflow Variables

- **`{agent#Output}`**: The result from a previously executed node within the *same* workflow. The `#` corresponds to
  the node's position (e.g., `{agent1Output}` for the first node, `{agent2Output}` for the second).
- **`{agent#Input}`**: A value passed from a parent workflow into a sub-workflow via `scoped_variables`. For example,
  `{agent1Input}` is the first variable passed from the parent.
- **`{custom_variable}`**: Any custom key defined at the top level of a workflow JSON (in the new dictionary format) is
  available as a variable. For example, if you define `"persona": "You are a pirate."`, you can use `{persona}` in any
  prompt within that workflow.

#### Conversation & Message Variables

- **`{chat_user_prompt_last_one}`**: The raw text content of the last message in the conversation. Also available for
  `two`, `three`, `four`, `five`, `ten`, and `twenty` messages.
- **`{templated_user_prompt_last_one}`**: The last message, but wrapped in the appropriate user/assistant prompt
  template tags. Also available for `two`, `three`, `four`, `five`, `ten`, and `twenty`.
- **`{chat_system_prompt}`**: The system prompt sent from the front-end client (e.g., a character card).
- **`{templated_system_prompt}`**: The front-end system prompt, wrapped in the appropriate system prompt template tag.
- **`{messages}`**: The raw, complete list of message objects. This is primarily useful for advanced templating with
  `jinja2` enabled on the node.

#### Date, Time & Context Variables

- **`{todays_date_pretty}`**: Today's date, e.g., "August 17, 2025".
- **`{todays_date_iso}`**: Today's date in ISO format, e.g., "2025-08-17".
- **`{current_time_12h}`**: The current time in 12-hour format, e.g., "8:48 PM".
- **`{current_time_24h}`**: The current time in 24-hour format, e.g., "20:48".
- **`{current_month_full}`**: The full name of the current month, e.g., "August".
- **`{current_day_of_week}`**: The full name of the current day, e.g., "Sunday".
- **`{current_day_of_month}`**: The day of the month as a number, e.g., "17".
- **`{time_context_summary}`**: A natural language summary of the conversation's timeline,
  e.g., "[Time Context: This conversation started 2 hours ago. The most recent message was sent 5 minutes ago.]".

#### Prompt Routing Variables

These variables are automatically available in categorization workflows and are populated from your routing
configuration file.

- **`{category_colon_descriptions}`**: A semicolon-separated list of categories and their descriptions. Example: "
  CODING: Any request which requires a code snippet...; FACTUAL: Requests that require factual information...".
- **`{category_colon_descriptions_newline_bulletpoint}`**: The same as above, but formatted as a bulleted list.
- **`{categoriesSeparatedByOr}`**: A simple list of just the category names. Example: "CODING or FACTUAL or
  CONVERSATIONAL".
- **`{categoryNameBulletpoints}`**: A bulleted list of just the category names.

#### Special Variables

- **`[TextChunk]`**: A special placeholder primarily used within memory-generation workflows (e.g., inside
  `fileMemoryWorkflowName` or `vectorMemoryWorkflowName`). It represents a specific block of conversation text that is
  being analyzed or summarized.

### Other Types of Nodes

#### The Memory System: Creators and Retrievers

The memory system has been fundamentally redesigned for performance and power. The core principle is a separation of
concerns between two types of nodes: **Creators** and **Retrievers**.

* **Memory Creators (Write Operations)**: These are computationally "heavy" nodes that analyze the conversation,
  generate new memories, and save them to files. This process is designed to run in the background, often after a
  workflow lock, so it doesn't slow down the user experience.
* **Memory Retrievers (Read Operations)**: These are "lightweight" nodes that perform fast, inexpensive lookups of
  existing memories to provide context for an AI's response.

This split allows you to build highly responsive workflows. You can retrieve existing context instantly at the beginning
of a workflow, get a fast reply to the user, and then trigger a memory creation node in the background to update the
memories with the latest turn of the conversation.

-----

### **Memory Creator Node**

This is the engine of the memory system. You only need one type of creator node, which handles all types of memory
generation.

#### QualityMemory

This is the primary and only node for **creating and updating** all persistent memories. When this node runs, it checks
the conversation history and, if enough new messages have been added, it will generate and save new memories. It can
create classic file-based memories or the new, powerful searchable vector memories, depending on your configuration.
This node does **not** return any text to the workflow; its only job is to write memories to storage in the background.

It's best practice to place this node at the end of a workflow, after a workflow lock, to ensure memory generation
doesn't delay the AI's response to the user.

```json
{
  "id": "create_memories_node",
  "type": "QualityMemory",
  "name": "Create or Update All Memories"
}
```

-----

### **Memory Retriever Nodes**

These nodes read from the memory files that the `QualityMemory` node creates. They are fast and provide different kinds
of context to your AI.

#### RecentMemorySummarizerTool

This node quickly **reads** the last few memory chunks from the long-term memory file (`<id>_memories.jsonl`). It's
excellent for providing the AI with immediate context on what was discussed recently. You can specify how many of the
most recent summarized chunks to retrieve.

Note that if a `discussionId` is not active, this node falls back to simply pulling the last `N` turns directly from the
current chat history, acting as a stateless memory provider.

```json
{
  "id": "get_recent_memories_node",
  "type": "RecentMemorySummarizerTool",
  "name": "Get Recent Memories",
  "maxTurnsToPull": 0,
  "maxSummaryChunksFromFile": 5,
  "customDelimiter": "\n------------\n"
}
```

* `maxSummaryChunksFromFile`: Specifies how many of the latest memory chunks to pull from the file.

#### FullChatSummary

This node **reads** the single, continuously updated "rolling summary" of the entire conversation from the chat summary
file (`<id>_summary.jsonl`). Use this to give the AI a high-level, condensed overview of the entire chat history from
start to finish. This node does **not** generate or update the summary; it only retrieves the existing one.

```json
{
  "id": "get_full_summary_node",
  "type": "FullChatSummary",
  "name": "Get Full Chat Summary"
}
```

#### VectorMemorySearch

This is the new **smart search** node, designed for Retrieval-Augmented Generation (RAG). It performs a powerful,
relevance-based search against the dedicated vector memory database (`<id>_vector_memory.db`). Instead of just getting
recent context, this node allows you to look up specific facts, topics, or details from anywhere in the conversation
history.

The search input **must be a string of keywords separated by semicolons (`;`)**. The node will find the memory chunks
most relevant to those keywords and return them, ranked by relevance.

```json
{
  "id": "smart_search_node",
  "type": "VectorMemorySearch",
  "name": "Search for Specific Details",
  "input": "Project Stardust;mission parameters;Dr. Evelyn Reed"
}
```

-----

### **Configuring Memory Generation (`_DiscussionId-MemoryFile-Workflow-Settings.json`)**

The behavior of the `QualityMemory` node is controlled by a dedicated configuration file for each `discussionId`. This
is where you decide what kind of memories to create and how they should be generated.

Here is a breakdown of the key configuration options:

```json
{
  // This is the master switch for the new memory system.
  // Set to true to create searchable vector memories.
  // Set to false to use the classic file-based memory system.
  "useVectorForQualityMemory": true,
  // ====================================================================
  // == Vector Memory Configuration (Only used if the above is true) ==
  // ====================================================================

  // For advanced users: specify a workflow to generate the structured JSON for a vector memory.
  "vectorMemoryWorkflowName": "my-vector-memory-workflow",
  // The LLM endpoint to use specifically for vector memory generation. Falls back to "endpointName".
  "vectorMemoryEndpointName": "gpt-4-turbo",
  // The preset for the specified endpoint. Falls back to "preset".
  "vectorMemoryPreset": "default_preset_for_json_output",
  // The max response size for the generated JSON. Falls back to "maxResponseSizeInTokens".
  "vectorMemoryMaxResponseSizeInTokens": 1024,
  // The target size in tokens for a chunk of conversation before it's processed.
  "vectorMemoryChunkEstimatedTokenSize": 1000,
  // The max number of new messages before forcing processing, even if token size isn't met.
  "vectorMemoryMaxMessagesBetweenChunks": 5,
  // How many of the most recent turns to ignore. This prevents summarizing an in-progress thought.
  "vectorMemoryLookBackTurns": 3,
  // ====================================================================
  // == File-based Memory Configuration (Only used if the switch is false) ==
  // ====================================================================

  // For advanced users: specify a workflow to generate the summary text for a file-based memory.
  "fileMemoryWorkflowName": "my-file-memory-workflow",
  // The system prompt used for the summarization LLM call when not using a workflow.
  "systemPrompt": "You are an expert summarizer. Your task is to extract key facts...",
  // The user prompt used for the summarization LLM call. [TextChunk] is replaced automatically.
  "prompt": "Please summarize the following conversation chunk: [TextChunk]",
  // The target size in tokens for a chunk of conversation before it's summarized.
  "chunkEstimatedTokenSize": 1000,
  // The max number of new messages before forcing a summarization, even if token size isn't met.
  "maxMessagesBetweenChunks": 5,
  // How many of the most recent turns to ignore for file-based memory generation.
  "lookbackStartTurn": 3,
  // ====================================================================
  // == General / Fallback LLM Settings                           ==
  // ====================================================================

  // The default LLM endpoint to use if a specific one (e.g., vectorMemoryEndpointName) isn't set.
  "endpointName": "default_endpoint",
  // The default preset to use.
  "preset": "default_preset",
  // The default max response size in tokens.
  "maxResponseSizeInTokens": 400
}
```

* **`useVectorForQualityMemory`**: This boolean is the most important setting. `true` enables the creation of a
  searchable SQLite database for the discussion. `false` falls back to the classic `.jsonl` memory file.
* **`vectorMemoryWorkflowName` / `fileMemoryWorkflowName`**: These keys allow you to specify the name of a sub-workflow
  to handle memory generation. This gives you complete control over the summarization process, allowing for multi-step
  logic (e.g., extracting topics then summarizing each one). If a workflow name is not provided, the system falls back
  to a direct LLM call using the `systemPrompt` and `prompt` fields.
* **`chunkEstimatedTokenSize` / `maxMessagesBetweenChunks`**: These values control how often the `QualityMemory` node
  decides to create a new memory chunk. A new memory is created if either the token count of new messages exceeds
  `chunkEstimatedTokenSize` OR the number of new messages exceeds `maxMessagesBetweenChunks`.

#### Parallel Processing Node

These nodes are used for memories and chat summary right now. These will break the memories up into chunks, and use
multiple LLMs to iterate through them. Every endpoint specified here will be utilized.

```json
{
  "title": "",
  "agentName": "",
  "systemPrompt": "You are an intelligent and capable assistant. Please answer the following request completely",
  "prompt": "",
  "multiModelList": [
    {
      "endpointName": "SocgWindowsPort5003"
    },
    {
      "endpointName": "SocgMacStudioPort5001"
    },
    {
      "endpointName": "SocgMacbookPort5004"
    }
  ],
  "preset": "Default",
  "type": "SlowButQualityRAG",
  "ragTarget": "",
  "ragType": "RecentMemory",
  "maxResponseSizeInTokens": 400,
  "addUserTurnTemplate": true
}
```

* IMPORTANT: Don't fiddle with these too much. Right now they are used for specific purposes and are not very flexible.
  You can change the following:
    * multiModelList: add or remove as many endpoints as you want here
    * preset: Change the preset to whatever you want
    * prompt and system prompt: if they are filled within the workflow, feel free to change them. Otherwise leave them
      alone.

#### Python Module Caller Node

This node can call any `.py` file with the `Invoke(*args, **kwargs)` method that returns a string (even an empty
string). What you do within Invoke is entirely up to you. This can be used to indefinitely extend WilmerAI's abilities.

```json
{
  "title": "Python Module Caller",
  "module_path": "D:/Temp/MyTestModule.py",
  "args": [
    "{agent1Output}"
  ],
  "kwargs": {},
  "type": "PythonModule"
}
```

### Full Text Wikipedia Offline API Caller Node

This node will make a call to
the [OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi)
and will pull back a response based on the promptToSearch that you pass in. You can use this text to pass
into other nodes for factual responses (see factual workflows in the sample users).

`NOTE: The below node is deprecated and will be replaced. The new node is right below it. I'm not removing it yet
in case someone is actively using it.`

```json
  {
  "title": "Querying the offline wikipedia api",
  "agentName": "Wikipedia Search Api Agent Three",
  "promptToSearch": "{agent1Output}",
  "type": "OfflineWikiApiFullArticle"
}
```

`NOTE: This is the new node. This node will require you to be using the newest version of the OfflineWikipediaTextApi.
If you are using an older version, you will not have the required "top_article" endpoint and this will crash.`

```json
  {
  "title": "Querying the offline wikipedia api",
  "agentName": "Wikipedia Search Api Agent Three",
  "promptToSearch": "{agent1Output}",
  "type": "OfflineWikiApiBestFullArticle"
}
```

In addition, there is a similar node that will take top N full articles where the user can specify the number of total
results to take and then the top N of these. If percentile, num_results, and top_n_articles are not specified then
defaults of 0.5, 10, and 3 will be used respectively. The output articles are given in order of score, where largest
scored article is first by default (descending). top_n_articles can also be negative, where a negative number will give
the results as ascending score rather then descending - this is useful when context is truncated by LLM.
NOTE: since the output from the wikipedia articles for this can be quite long, you may need to pay attention to the
Model Endpoint that this is output to and possibly increase the "maxContextTokenSize" to handle the larger output size.
Using ascending results might help with this.

```json  
  {
  "title": "Querying the offline wikipedia api",
  "agentName": "Wikipedia Search Api Agent Three",
  "promptToSearch": "{agent1Output}",
  "type": "OfflineWikiApiTopNFullArticles",
  "percentile": 0.4,
  "num_results": 40,
  "top_n_articles": 4
}
```

The configuration for these nodes can be found in the user json.

```json
{
  "useOfflineWikiApi": false,
  "offlineWikiApiHost": "127.0.0.1",
  "offlineWikiApiPort": 5728
}
```

When set to false, the node is hardcoded to respond that no additional information was found.

### First Paragraph Text Wikipedia Offline API Caller Node

This is an alternative setting to the full text. txtapi-wikipedia by default returns the first
paragraph of the wiki article. If that is all you need, then this endpoint will return that.

The only difference from the previous node is the type.

```json
{
  "title": "Querying the offline wikipedia api",
  "agentName": "Wikipedia Search Api Agent Three",
  "promptToSearch": "{agent1Output}",
  "type": "OfflineWikiApiPartialArticle"
}
```

### Get Custom File

This node allows you to load a custom text file in a workflow. The text file can contain anything that you want,
and will be treated as any other output node. So if this node is the first in your workflow, then you can reference
the file using `{agent1Output}` in future nodes of that workflow, for example.

- `filepath`: The specific file you want to load. This must be a single .txt file
- `delimiter`: The separator that you use in the file to separate different topics, if applicable.
- `customReturnDelimiter`: What you'd like to replace the delimiter with when returning the text from the file
  as an agent output.

Example for delimiter: perhaps in your file you have 5 paragraphs, each separated by 2 newlines. You'd like to
break those into individual items, separated by asterisks. Your delimiter might be "\n\n" while your custom
delimiter might be "\n\n******\n\n" This would cause the below

```text
paragraph 1

paragraph 2
```

to become

```text
paragraph 1

******

paragraph 2
```

This node can be added with the following syntax:

```json
{
  "title": "Custom File Grabber",
  "type": "GetCustomFile",
  "filepath": "D:\\Temp\\some_custom_file.txt",
  "delimiter": "\n\n",
  "customReturnDelimiter": "\n\n"
}
```

### Workflow Lock

A workflow lock acts as a way to lock a workflow at a certain point during asynchronous operations, so that you don't
encounter race conditions of two instances of a workflow crashing into each other via consecutive calls.

To put it more simply, lets use an example workflow:

```text
Node 1: "GetCurrentSummaryFromFile" type node. This does NOT generate a chat summary;
it only pulls the existing summary out of the file if one is there.

Node 2: "RecentMemorySummarizerTool" type node. This does NOT generate memories; it
only pulls existing memories out of the file if they exist.

Node 3: Responder node. Just a regular chat node with no "type" that would output text.
However, since we want this one to respond to the user, we will be setting `returnToUser`
to true. This will force this node to output its response to the user, even though it's
only halfway through the workflow.

Node 4: "WorkflowLock" type node. This node will generate a workflow lock at this point.
We will give the WorkflowLock an ID, and until that workflow lock is released, any node
of this type with that ID for this Wilmer instance will not be allowed to progress past
the lock.

Node 5: "FullChatSummary" type node. This will generate memories and generate a chat
summary. This can be a very long and intensive process. 
```

Ok, so looking at the above, let's make a couple of assumptions to help make workflow locks make sense.

- Lets assume that you own 2 computers, both serving a different LLM. Maybe Llama 3.1 8b on computer A, and Qwen2.5 7b
  on Computer B.
- The LLM you use to respond to the user in Node 3 is on Computer A, using Llama 3.1
- The LLM you use to generate memories and chat summaries in Node 5 is on Computer B, using Qwen2.5
- For the below example, lets assume you have 200 messages in your chat, and have not yet generated
  a memory or chat summary file.
- You are using a streaming workflow; ie your front end has streaming enabled. If this is not true,
  then node 3 won't respond to you and the workflow lock is useless. Most people have this on.

Based on these assumptions, lets step through the workflow.

1) You send a message.
2) Nodes 1 and 2 gathering your memories and chat summary file. They don't GENERATE anything, they
   only pull what exists from the file. If nothing exists, they pull nothing
3) Node 3 utilizes the outputs of Nodes 1 and 2, the memories and chat summary, to generate a response.
   Because respondToUser is true, that response is sent to the front end UI for the user to read.
4) Node 4, the workflow lock, engages a lock on whatever the ID is. Lets say the ID is "MyMemoryLock". So
   now Wilmer has registered that there is a workflow lock called "MyMemoryLock", and it is turned on.
5) The FullChatSummary node begins generating memories and a summary. Because you have 200 messages, this will
   take around 5 minutes to complete.

Ok, so you likely got your response from Node 3 in about 10 seconds. But now your memories and summary are being
generated, and that could take up to 5 minutes, so... no more robits for you for 5 minutes?

Nope. Thanks to the workflow lock, that isn't the case.

Lets consider if you immediately send another message after receiving the response to your UI from Node 3, meaning
you that start talking to the AI while there is still 4 minutes of work left for Node 5 on generating memories and
the chat summary. Also remember that Computer A was used to respond to you, while Computer B is the one generating
the memories.

1) You send a message.
2) Nodes 1 and 2 gathering your memories and chat summary file. They don't GENERATE anything, they
   only pull what exists from the file. If nothing exists, they pull nothing
3) Node 3 utilizes the outputs of Nodes 1 and 2, the memories and chat summary, to generate a response.
   Because respondToUser is true, that response is sent to the front end.
4) Workflow hits the workflow lock node. It sees that "MyMemoryLock" is engaged, and ends the workflow here,
   not progressing past this point.

So what happened? You sent a message, the LLM on Computer A (your responder AI, which currently has nothing
else to do but respond to you) responds to you, and then the workflow lock stops the workflow immediately after.
Computer B is still busy generating memories and summaries from your first message, so we don't want to send
another request to it yet. But computer B being busy means nothing for computer A, which is ready to go and will
happily keep talking to you.

This means that, using workflow locks, you can keep talking to your LLM while memories and summaries are being
generated. In this example we used small models, but in reality we might use large ones. For example, Socg might
use a Mac Studio with Llama 3.1 70b running, and a Macbook with another instance of Llama 3.1 70b running. Both of
those, on a mac, can take up to 2 minutes to respond on a lengthy prompt, so writing memories and summaries can take
forever. Thanks to this workflow locks, there is no need to wait for those memories/summaries to complete, as the
conversation can continue using the Studio to respond while the Macbook works tirelessly in the background
updating memories/summaries.

```json
  {
  "title": "Workflow Lock",
  "type": "WorkflowLock",
  "workflowLockId": "FullCustomChatSummaryLock"
}
```

**IMPORTANT**: Workflow locks automatically unlock when a workflow has finished its task, and workflow locks
automatically release when Wilmer is restarted. Each user gets their own workflow lock tracking,
which is done in the user's sqlLite database (the path to which can be configured in the user json). Workflow locks
are tracked by a combination if ID, user, and API instance. So as long as you are in the same instance of Wilmer and
the same User, you can use the same workflow id in as many workflows as you want. Meaning 1 workflow can cause locks
in other workflows, if that's what you desire.

Workflow locks work best in multi-computer setups.

### Image Processor

The image processor node allows you to utilize Ollama to get information about any images sent to the backend via the
standard Ollama images API request for either the Wilmer exposed api/chat or api/generate endpoints.

So, essentially- if you connect Open WebUI to Wilmer, it will connect to an endpoint Wilmer exposes that is compatible
with Ollama's api/chat api endpoint. If you send a picture in Open WebUI, that will be sent to Wilmer as if it were
going to Ollama. Wilmer will see the image, and if you have an ImageProcessor node, that node will caption the image so
that you can send it to your main text LLMs later in the workflow. The ImageProcessor node currently requires that the
endpoint be of the `OllamaApiChatImageSpecific` ApiType, but support for KoboldCpp should be coming soon as well.

In the event that no image is sent into a workflow with the ImageProcessor node, the node will return a hardcoded
string of "There were no images attached to the message".

```json
  {
  "title": "Image Processor",
  "agentName": "Image Processing Agent One",
  "type": "ImageProcessor",
  "systemPrompt": "There is currently a conversation underway between a user and an AI Assistant in an online chat program. The AI Assistant has no ability to see images, and must rely on a written description of an image to understand what image was sent.\nWhen given an image from the user, please describe the image in vivid detail so that the AI assistant can know what image was sent and respond appropriately.",
  "prompt": "The user has sent a new image in a chat. Please describe every aspect of the image in vivid detail. If the image appears to be a screenshot of a website or desktop application, describe not only the contents of the programs but also the general layout and UX. If it is a photo or artwork, please describe in detail the contents and any styling that can be identified. If it is a screenshot of a game that has menu options or a HUD or any sort of interactive UX, please be sure to summarize not only what is currently occurring in the screenshot but also what options appear to be available in the various UI elements. Spare no detail.",
  "endpointName": "Socg-OpenWebUI-Image-Endpoint",
  "preset": "_Socg_OpenWebUI_Image_Preset",
  "maxResponseSizeInTokens": 2000,
  "addUserTurnTemplate": true,
  "addDiscussionIdTimestampsForLLM": true,
  "addAsUserMessage": true,
  "message": "[SYSTEM: The user recently added images to the conversation. The images have been analyzed by an advanced vision AI, which has described them in detail. The descriptions of the images can be found below:```\n[IMAGE_BLOCK]]\n```]"
}
```

- `addAsUserMessage`: If this is set to true, not only will the node put the output from the image model into an
  agentOutput to be used later, but it will also add a new message to the conversation collection being processed
  containing that as well. So essentially- every LLM that is called after this node will see 1 more message added
  to the conversation history- a message with a role of 'user' that will contain the output of the LLM in a particular
  format specified in the next field, message. If this is false, the node will act like a normal node and only generate
  an agentOutput
- `message`: This is used together with 'addAsUserMessage' being true. This is the message that will be added to the
  chat history. There is a special variable for this called **`[IMAGE_BLOCK]`** that will be replaced with whatever
  the image llm output from this node; ie `[IMAGE_BLOCK]` will be replaced with whatever the agentOutput value of this
  node will be. This node is optional; there is a hardcoded message that will be used as default if you do not specify
  one. The example message I put above is the hardcoded message it would use.

**NOTE**- If addAsUserMessage is true, it will not affect the agentOutput. The node will still produce one as normal,
and that output will be whatever the LLM responded with. The agentOutput will not contain the value of `message`.

**IMPORTANT**: The ImageProcessor node currently does not support streaming; this only responds as non-streaming, and
is meant to be used in the middle of a workflow as a captioner, not as the responder for a workflow.

**IMPORTANT**: If you use this with Open WebUI it's fine out of the box, but if you use this in SillyTavern while
connected to Wilmer as Text Completion -> Ollama, simply be sure to go to the 3 squares icon at the top right
(Extensions) -> Click "Image Captioning" section, and put the Wilmer prompt template user tag in front of whatever
caption prompt you have. So instead of the default `"What’s in this image?"` it needs to be `"[Beg_User]What’s in this
image?"` Captioning seems to work fine with this change. I will be adding screenshots and/or a quickguide
for this once I'm done with my testing.

---

### **Custom Workflow Node**

The **`CustomWorkflow` Node** allows you to execute an entire, separate workflow from within the current workflow. This
is incredibly powerful for encapsulating reusable logic, breaking down complex processes into smaller, manageable parts,
and orchestrating multi-step agentic tasks. The final result of the child workflow is captured and stored in the
parent's state, accessible to subsequent nodes.

#### **Properties**

* `type` (string, required): Must be `"CustomWorkflow"`.
* `workflowName` (string, required): The filename of the custom workflow to execute (e.g., `"MySubWorkflow.json"`).
* `is_responder` (boolean, optional, default: `false`): Determines if this node provides the final, user-facing
  response.
    * If `true`, the sub-workflow's final output is returned to the user, and the parent workflow terminates. If the
      initial request was for a streaming response, this sub-workflow will stream its output.
    * If `false` (or omitted), the sub-workflow runs "silently." Its final output is captured and stored in an
      `agent#Output` variable for the parent workflow to use, but it is not sent to the user.
* `scoped_variables` (array of strings, optional): **(Recommended)** A list of values to pass from the parent workflow
  into the child workflow's global scope. These values become available to *all nodes* in the child workflow as
  `{agent1Input}`, `{agent2Input}`, etc., based on their order in the array. This is the most flexible way to provide a
  child workflow with the context it needs.
* `firstNodeSystemPromptOverride` (string, optional): Overrides the `systemPrompt` for the very first node in the child
  workflow. This is a legacy method for passing data.
* `firstNodePromptOverride` (string, optional): Overrides the `prompt` for the very first node in the child workflow.
  This is also a legacy method for passing data.

#### **Syntax**

```json
{
  "title": "Call a Sub-Workflow to Summarize Text",
  "type": "CustomWorkflow",
  "workflowName": "SummarizerWorkflow.json",
  "is_responder": false,
  "scoped_variables": [
    "{agent1Output}",
    "A custom static string value"
  ],
  "firstNodeSystemPromptOverride": "You are a helpful summarization assistant. The user has provided the following text from a previous step: {agent1Output}",
  "firstNodePromptOverride": "Please summarize the provided text."
}
```

-----

### **Conditional Custom Workflow Node**

The **`ConditionalCustomWorkflow` Node** extends the `CustomWorkflow` node with powerful branching logic. It dynamically
selects and executes a specific sub-workflow based on the resolved value of a conditional variable (e.g., the output
from a previous node). This allows you to create adaptive workflows that react differently based on runtime conditions.

Each potential path, or "route," can also have its own unique prompt overrides, giving you fine-grained control over how
each selected sub-workflow is initiated.

#### **Properties**

* `type` (string, required): Must be `"ConditionalCustomWorkflow"`.
* `conditionalKey` (string, required): A variable placeholder (e.g., `{agent1Output}`) whose resolved value determines
  which workflow to execute.
* `conditionalWorkflows` (object, required): A dictionary that maps the possible values of `conditionalKey` to workflow
  filenames.
    * **`Default`** (string, optional): A special key that specifies a fallback workflow to run if the `conditionalKey`'
      s value does not match any other key in the map.
* `is_responder` (boolean, optional, default: `false`): Functions identically to the `CustomWorkflow` node, determining
  if the selected sub-workflow provides the final user-facing response.
* `scoped_variables` (array of strings, optional): **(Recommended)** Functions identically to the `CustomWorkflow` node.
  The provided variables are passed into whichever sub-workflow is chosen by the conditional logic.
* `routeOverrides` (object, optional): A dictionary specifying prompt overrides for each potential route. The keys in
  this object should correspond to the keys in `conditionalWorkflows`. Each route can define:
    * `systemPromptOverride` (string, optional): Overrides the system prompt for the first node in the selected
      workflow.
    * `promptOverride` (string, optional): Overrides the user prompt for the first node in the selected workflow.

#### **Syntax**

```json
{
  "title": "Route to a Specific Coding Model",
  "type": "ConditionalCustomWorkflow",
  "conditionalKey": "{agent1Output}",
  "conditionalWorkflows": {
    "Python": "PythonCodingWorkflow.json",
    "JavaScript": "JavaScriptCodingWorkflow.json",
    "Default": "GeneralCodingWorkflow.json"
  },
  "is_responder": true,
  "scoped_variables": [
    "{lastUserMessage}"
  ],
  "routeOverrides": {
    "Python": {
      "systemPromptOverride": "You are an expert Python programmer. The user's request is: {agent1Input}"
    },
    "JavaScript": {
      "systemPromptOverride": "You are a master JavaScript developer. The user's request is: {agent1Input}"
    }
  }
}
```

#### **Behavior and Known Issue**

1. **Conditional Execution**: The node resolves the value of `conditionalKey`. It then performs a **case-insensitive**
   search for that value as a key within the `conditionalWorkflows` map. For example, if `{agent1Output}` resolves to
   `"python"`, `"Python"`, or `"PYTHON"`, it will correctly match the `"Python"` key and select
   `PythonCodingWorkflow.json`. If no match is found, it will use the workflow specified under the `Default` key.

2. **⚠️ Known Issue: Route Override Key Casing**: When looking for overrides in the `routeOverrides` map, the logic is
   different. The resolved `conditionalKey` is normalized to lowercase and then **capitalized** (e.g., `"python"`
   becomes `"Python"`). This means the keys in your `routeOverrides` object **must be capitalized** to be found.

    * ✅ **Correct**: `"Python"`, `"JavaScript"`
    * ❌ **Incorrect**: `"python"`, `"javascript"`

3. **Fallback Behavior**: If `routeOverrides` is not defined for a matching route, the selected sub-workflow will
   execute using its own default prompts for its first node.

-----

### **Passing Data from a Parent Workflow to a Child Workflow**

A critical concept to understand is that a child workflow runs in an isolated context. It **cannot** directly access the
outputs of the parent workflow (e.g., `{agent1Output}`, `{agent2Output}`, etc., from the parent are unavailable inside
the child).

There are two primary mechanisms to pass data from the parent to the child.

#### **Method 1: `scoped_variables` (Recommended Method)**

This is the most powerful and flexible method. The `scoped_variables` property lets you define a list of values from the
parent's context that you want to make available globally within the child.

* **How it Works**: The values you list in `scoped_variables` are bundled and passed to the child workflow. Inside the
  child workflow, they can be accessed *at any node* using the special `{agent#Input}` syntax. The numbering corresponds
  to the order in the array (0-indexed array, 1-indexed variable).

    * The 1st item in `scoped_variables` becomes `{agent1Input}`.
    * The 2nd item becomes `{agent2Input}`.
    * ...and so on.

* **Example**:

    * Parent Node Config:
      ```json
      "scoped_variables": [
        "{agent1Output}",
        "{lastUserMessage}"
      ]
      ```
    * Usage anywhere in the Child Workflow's JSON:
      ```json
      "prompt": "The text to analyze is '{agent1Input}' and the user's original question was '{agent2Input}'."
      ```

#### **Method 2: Prompt Overrides (Legacy Method)**

This was the original method for passing data. You can embed parent variables directly into the
`firstNodeSystemPromptOverride` or `firstNodePromptOverride` properties.

* **How it Works**: The variable placeholders are resolved in the parent's context *before* the child workflow is
  called. The resulting string is then forced upon the first node of the child workflow, replacing its original prompt.
* **Limitation**: This method only makes the data available to the **first node** of the child workflow. If you need the
  data in later nodes, you must have the first node explicitly output it so it can be accessed via that child's
  `{agent1Output}`. This is why `scoped_variables` is now the recommended approach.

### **Receiving Data from a Child Workflow**

The process of getting the final result back from a child workflow is simple. The entire final output of the
sub-workflow (i.e., the result of its last or "responder" node) is treated as the output of the `CustomWorkflow` node
itself.

* **Example**: If a `CustomWorkflow` node is the **4th node** in your parent workflow, its final, resolved output will
  be stored in the parent's `{agent4Output}`, ready to be used by node 5 and beyond.

---

## Understanding Memories

WilmerAI's memory system has undergone a significant evolution, making it more powerful, flexible, and intelligent. It's
designed to provide rich, searchable context for your conversations, ensuring the AI remains coherent and knowledgeable
over long discussions. This guide will provide an exhaustive breakdown of how the new system works.

The core architecture is built on a few key principles:

1. **Three Types of Memory:** The system supports three distinct memory types, each with a specific purpose:
   chronological **Long-Term Memory** (file-based), a holistic **Rolling Chat Summary**, and a powerful, searchable *
   *Vector Memory** for RAG.
2. **Separation of Concerns:** The system is split into **Creator** nodes, which perform the computationally expensive
   work of writing memories, and **Retriever** nodes, which perform fast, inexpensive reads. This split ensures your
   chat remains responsive even while memories are being updated in the background.
3. **Workflow-Driven:** Memory operations are implemented as nodes within the workflow engine, giving you explicit
   control over when and how memories are created and accessed.

-----

### How Memories are Enabled

The entire persistent memory system is activated by a single tag: `[DiscussionId]`. You must include this tag anywhere
in your conversation (system prompt, user prompt, or messages) to enable the creation and retrieval of long-term
memories.

`[DiscussionId]#######[/DiscussionId]` (where `#######` is any unique identifier).

For example, `[DiscussionId]project_alpha_123[/DiscussionId]`. Wilmer will automatically remove this tag before sending
prompts to the LLM.

> **NOTE:** It's recommended not to put the `DiscussionId` in a character's main definition or system prompt if you want
> separate conversations with that character to have separate memories. Placing it in an author's note or the first
> message of a chat is often a better practice. Some front-ends support variables that can help create unique IDs, for
> example: `[DiscussionId]{{char}}_2025-08-17[/DiscussionId]`.

-----

### The Three Types of Memory

When a `DiscussionId` is active, the system can maintain up to three distinct files in your `Public/` directory, each
serving a specific purpose.

#### 1\. Long-Term Memory (File-Based)

This system provides a chronological, diary-like record of the conversation.

* **Memory File (`<id>_memories.jsonl`)**: This is the classic memory file. Wilmer groups messages into chunks, uses an
  LLM to summarize them, and saves these summaries sequentially. It's a detailed, append-only ledger of what's been
  discussed, with each summary chunk linked via a hash to the last message it was based on.

#### 2\. Rolling Chat Summary

This provides a high-level narrative of the entire conversation, updated periodically.

* **Chat Summary File (`<id>_summary.jsonl`)**: This file maintains a single, continuously updated story of the entire
  conversation. It synthesizes the chunks from the Long-Term Memory file into a holistic overview, giving the AI a
  bird's-eye view of everything that has happened so far.

#### 3\. Vector Memory (The Smart Search System) 🧠

This is the most powerful addition to the memory system. It creates a dedicated, intelligent database for each
discussion, enabling highly relevant, keyword-based search for Retrieval-Augmented Generation (RAG).

* **Vector Memory Database (`<id>_vector_memory.db`)**: Instead of just a text summary, vector memories are stored as
  structured data in a dedicated **SQLite database**. When a memory is created, it's saved with rich metadata. The
  system uses SQLite's FTS5 extension to perform powerful full-text searches across this metadata, allowing the AI to
  perform a "smart search" to find the most relevant pieces of information about a specific topic.

-----

### Using Memories in a Workflow: Creators vs. Retrievers

This separation is crucial for performance. Writing and summarizing memories can take time. By splitting the process,
you can design workflows where the AI responds instantly using existing memories, while the creation of new memories
happens in the background.

#### Memory Creation Nodes (The "Heavy Lifting")

These nodes perform the computationally expensive work of generating and saving memories.

* **`QualityMemory`**: This is the main node for **creating and updating** your **Long-Term (File-Based)** and **Vector
  ** memories. You place this in your workflow where you want memory generation to happen (usually at the very end).
  It's the engine that powers the main memory system and will generate either file-based or vector memories based on
  your configuration.
* **`chatSummarySummarizer`**: This is a special-purpose creator node used exclusively for generating and updating the *
  *Rolling Chat Summary** (`<id>_summary.jsonl`).

#### Memory Retrieval Nodes (The "Fast Readers")

These nodes are lightweight and designed to quickly read existing memories to provide context for an AI's response.

* **`RecentMemory` / `RecentMemorySummarizerTool`**: Reads the last few summary chunks from your Long-Term Memory File (
  `<id>_memories.jsonl`). It's great for giving an AI general context of what just happened.
* **`FullChatSummary`**: Reads the entire Rolling Chat Summary from `<id>_summary.jsonl`. Use this to give the AI the
  complete "story so far."
* **`VectorMemorySearch`**: The powerful **smart search** node. It performs a keyword search against the Vector Memory
  database (`<id>_vector_memory.db`) to find the most relevant information for RAG.

-----

### Configuration: The Master Settings File

All settings for how the `QualityMemory` node generates memories are controlled by a single configuration file:
`_DiscussionId-MemoryFile-Workflow-Settings.json`.

The most important setting is the master switch that determines which memory system to use:

* **`useVectorForQualityMemory`**: If `false` (the default), the `QualityMemory` node will write to the classic
  Long-Term Memory (`.jsonl` files). If `true`, it will create the powerful, searchable Vector Memories in the SQLite
  database.

Below is an example of the expanded settings file:

```json
{
  "Display_Only_Description": "Settings for the QualityMemory node.",
  "useVectorForQualityMemory": true,
  "vectorMemoryWorkflowName": "my-vector-memory-workflow",
  "vectorMemoryEndpointName": "Your-Endpoint",
  "vectorMemoryPreset": "_Your_Preset",
  "vectorMemoryMaxResponseSizeInTokens": 2048,
  "vectorMemoryChunkEstimatedTokenSize": 1000,
  "vectorMemoryMaxMessagesBetweenChunks": 5,
  "vectorMemoryLookBackTurns": 3,
  "fileMemoryWorkflowName": "my-file-memory-workflow",
  "systemPrompt": "You are a summarizer. [Memory_file] [Chat_Summary]",
  "prompt": "Summarize this chunk: [TextChunk]",
  "endpointName": "Your-Endpoint",
  "preset": "_Your_MemoryChatSummary_Preset",
  "maxResponseSizeInTokens": 250,
  "chunkEstimatedTokenSize": 2500,
  "maxMessagesBetweenChunks": 20,
  "lookbackStartTurn": 7
}
```

#### Breakdown of Configuration Fields

* **`useVectorForQualityMemory`**: The master switch. `true` for Vector DB, `false` for file-based `.jsonl`.

* **General Settings**:

    * **`chunkEstimatedTokenSize` / `maxMessagesBetweenChunks`**: These work together. A memory is generated when the
      conversation history since the last memory point reaches `chunkEstimatedTokenSize` **OR** when
      `maxMessagesBetweenChunks` have passed, whichever comes first. This ensures memories are created regularly.
    * **`lookbackStartTurn`**: Tells Wilmer to ignore the last N messages when creating memories. This is useful for
      preventing static text or system messages from being included in memory summaries.

* **Vector-Specific Settings**: The settings prefixed with `vectorMemory...` apply *only* when
  `useVectorForQualityMemory` is `true`, allowing you to tune vector memory generation independently.

* **File-Based Settings**: The classic settings (`systemPrompt`, `prompt`, `endpointName`, etc.) apply *only* when
  `useVectorForQualityMemory` is `false`.

-----

### Implementation Guide: Putting It All Together

This section provides exhaustive, step-by-step instructions for creating and using each memory type.

#### How to Create & Use Vector Memories (RAG)

Vector memory is the most powerful option for RAG. It involves creating a workflow that outputs structured JSON data.

**Step 1: Configure for Vector Memory**

In `_DiscussionId-MemoryFile-Workflow-Settings.json`, enable vector memory and specify the name of the workflow that
will generate it.

```json
{
  "useVectorForQualityMemory": true,
  "vectorMemoryWorkflowName": "my-vector-fact-extraction-workflow"
}
```

**Step 2: Build the Generation Workflow**

Your vector memory workflow must have a final node that outputs a **JSON string**. This string can represent a single
JSON object or, more commonly, an array of objects. Each object represents a single "memory" or "fact" to be stored in
the database.

Based on the system's database schema, each JSON object **must** contain the following keys to be indexed for search:
`title`, `summary`, `entities`, and `key_phrases`. The value for `summary` is also used as the primary `memory_text`.
You can include other keys (like `sentiment` or `topics` from the example), but they will only be stored as metadata and
not used in the default search.

Here is a complete, three-step example workflow (`my-vector-fact-extraction-workflow.json`):

```json
[
  {
    "title": "LLM Determine New Memories",
    "agentName": "Memory Finder Agent One",
    "type": "Standard",
    "systemPrompt": "You are a Fact Extraction Agent... Your role is crucial for maintaining the illusion of long-term memory... Focus on the Subject, Not the Conversation... Timelessness... Self-Contained...",
    "prompt": "Analyze the following new messages in the chat and extract persistent facts for the Fact Database:\n\n<new_messages>\n{agent1Input}\n</new_messages>\n\nFormat the output as a list of bullet points...",
    "endpointName": "Your-Endpoint",
    "preset": "_Your_MemoryChatSummary_Preset",
    "maxResponseSizeInTokens": 2000,
    "returnToUser": false
  },
  {
    "title": "LLM adding context to the memories",
    "agentName": "Memory Finder Agent Two",
    "type": "Standard",
    "systemPrompt": "You are an AI assistant that structures factual data. When given a bullet point list of memories, and the messages they were pulled from, please add additional structured information as required about each memory.",
    "prompt": "A new series of messages arrived in the chat...:\n\n<new_messages>\n{agent1Input}\n</new_messages>\n\nNew memories were generated...:\n\n<new_memories>\n{agent1Output}\n</new_memories>\n\nFor each memory, please do the following:\n- Separate the memories with headers ('# Memory 1', etc.).\n- Specify a `title`: A concise, 5-10 word headline.\n- Write a `summary`: the exact text of the memory from the bullet point list.\n- Specify `entities`: a list of important proper nouns.\n- Specify `key_phrases`: A list of key conceptual phrases.\n\nPlease respond with the structured memory list now.",
    "endpointName": "Your-Endpoint",
    "preset": "_Your_MemoryChatSummary_Preset",
    "maxResponseSizeInTokens": 2000,
    "returnToUser": false
  },
  {
    "title": "LLM Format Memories into JSON Array",
    "agentName": "Memory Finder Agent Three",
    "type": "Standard",
    "systemPrompt": "You are a JSON formatting agent. When given a list of structured memories, format them into a valid JSON array of objects and respond ONLY with the formatted JSON. Do not include any other text, comments, or markdown.",
    "prompt": "Below is a generated list of memories:\n\n<memories>\n{agent2Output}\n</memories>\n\nPlease take the above memories and reformat them into a single, valid JSON array of objects. The final output must be only the raw JSON text.",
    "endpointName": "Your-Endpoint",
    "preset": "_Your_MemoryChatSummary_Preset",
    "maxResponseSizeInTokens": 2000,
    "returnToUser": true
  }
]
```

* **Workflow Input**: The system automatically injects the raw conversation chunk into your workflow as `{agent1Input}`.
* **Final Workflow Output**: The final node (`returnToUser: true`) must produce a raw JSON string like this:

<!-- end list -->

```json
[
  {
    "title": "Inspection Report for House in Florida",
    "summary": "The inspection for the prospective white house in Florida revealed some termite damage in the garage, but was otherwise positive. A repair quote is being obtained.",
    "entities": [
      "Florida"
    ],
    "key_phrases": [
      "inspection report",
      "termite damage",
      "repair quote"
    ]
  },
  {
    "title": "Bob's Annual Summer Resort",
    "summary": "Bob visits an annual summer resort that features waterfront access, a private beach, spa facilities, and is built into a former country club.",
    "entities": [
      "Bob"
    ],
    "key_phrases": [
      "annual summer resort",
      "private beach",
      "spa facilities"
    ]
  }
]
```

**Step 3: Retrieving Vector Memories**

Use the `VectorMemorySearch` node in your workflow. It takes a single string input containing your search terms. *
*Keywords must be separated by semicolons (`;`)**. The system sanitizes each term and searches for any of them (using
`OR` logic), ranking the results by relevance.

* **Example Input for `VectorMemorySearch` node**: `"Florida house inspection; termite damage; bob's vacation"`
* **Note**: The system will process a maximum of 60 keywords to prevent overly complex queries.

#### How to Create & Use File-Based Memories

This is the classic, chronological memory system.

**Step 1: Configure for File-Based Memory**

In `_DiscussionId-MemoryFile-Workflow-Settings.json`, ensure vector memory is disabled.

```json
{
  "useVectorForQualityMemory": false
}
```

**Step 2: Choose a Creation Method**

* **A) Workflow-Based (Recommended):** Specify a workflow name in the settings file via `fileMemoryWorkflowName`. The
  system will execute this workflow, and the final output **must be a single summarized text block**. The system injects
  the following context, available in your prompts:
    * `{agent1Input}`: The raw text chunk to be summarized.
    * `{agent2Input}`: The most recent memory chunks.
    * `{agent3Input}`: The full history of all memory chunks.
    * `{agent4Input}`: The current rolling chat summary.
* **B) Direct LLM Call (Legacy):** If `fileMemoryWorkflowName` is not set, the system falls back to a direct LLM call
  using the `prompt` and `systemPrompt` from the settings file. You can use these special variables in your prompts:
    * `[TextChunk]`: The chunk of messages to be summarized.
    * `[Memory_file]`: The last 3 memories generated.
    * `[Full_Memory_file]`: All currently generated memories.
    * `[Chat_Summary]`: The current rolling chat summary.

**Step 3: Retrieving File-Based Memories**

Use the `RecentMemory` or `RecentMemorySummarizerTool` node in your workflow. It will read the most recent summary
chunks from the `<id>_memories.jsonl` file.

#### How to Create & Use the Rolling Chat Summary

The rolling summary is generated by a separate, dedicated workflow node.

**Step 1: The `chatSummarySummarizer` Node**

To create or update the rolling summary, you must include a node with `"type": "chatSummarySummarizer"` in your
workflow. This is a special, single-node workflow.

**Step 2: Building the Summary Workflow**

Here is a complete example of a chat summary workflow. Note the special properties `loopIfMemoriesExceed` and
`minMemoriesPerSummary` which are required.

```json
[
  {
    "title": "Chat Summarizer",
    "agentName": "Chat Summarizer Agent",
    "type": "chatSummarySummarizer",
    "systemPrompt": "You are an expert summarizer. Condense the provided information into a coherent narrative summary.",
    "prompt": "The current chat summary is:\n[CHAT_SUMMARY]\n\nThe newest memories since the last summary are:\n[LATEST_MEMORIES]\n\nPlease update the summary to incorporate the new information from the latest memories.",
    "endpointName": "Your-Endpoint",
    "preset": "_Your_MemoryChatSummary_Preset",
    "maxResponseSizeInTokens": 2000,
    "loopIfMemoriesExceed": 3,
    "minMemoriesPerSummary": 2
  }
]
```

* **Workflow Properties**:
    * `loopIfMemoriesExceed`: When regenerating many memories at once, this tells the system to update the summary after
      every `N` new memories are created. This improves quality by feeding the summary back into the next memory
      generation cycle.
    * `minMemoriesPerSummary`: During a normal conversation, this prevents the summary from updating until at least `N`
      new memories have been generated since the last update.
* **Prompt Variables**:
    * `[CHAT_SUMMARY]`: The current rolling chat summary from the file.
    * `[LATEST_MEMORIES]`: The new memory chunks created since the last summary was written.

**Step 3: Retrieving the Summary**

Use the `FullChatSummary` node to get the complete text from the `<id>_summary.jsonl` file.

-----

### Advanced Topics: Tracking and Regeneration

#### How Memories are Stored and Tracked

The system has robust mechanisms to avoid reprocessing the same conversation history.

* **File-Based Tracking**: Each summary in `<id>_memories.jsonl` is stored alongside a **hash** of the last message it
  was based on. When the `QualityMemory` node runs, it finds the last hash and compares it to the chat history to see
  where to resume processing. **Pitfall**: If you edit or delete a message that was hashed, the system may lose its
  place and re-summarize a large portion of your chat, potentially creating duplicate memories.

* **Vector-Based Tracking**: This system is more robust. Inside the `<id>_vector_memory.db` file, a dedicated
  `vector_memory_tracker` table stores the hash of the last message processed. This prevents reprocessing messages even
  if earlier parts of the conversation are edited.

#### Redoing Memories

To regenerate memories from scratch (e.g., after improving your prompts), you must **delete all memory files** for that
`DiscussionId`.

> **NOTE:** Always back up your memory files before modifying or deleting them, unless you are certain you want to
> rebuild them completely.

Delete all associated files from the `Public/` directory:

1. `<id>_memories.jsonl` (Long-Term Memory)
2. `<id>_summary.jsonl` (Rolling Summary)
3. `<id>_vector_memory.db` (Vector Memory)

The next time you run a workflow containing the creator nodes (`QualityMemory`, `chatSummarySummarizer`), the system
will see the files are missing and regenerate everything from the complete chat history. This is also a useful way to *
*consolidate memories**, as regeneration prioritizes the `chunkEstimatedTokenSize` over `maxMessagesBetweenChunks`,
often resulting in fewer, more comprehensive memory chunks.

### Parallel Processing

For handling extensive conversations, the app employs a parallel processing node for chat summaries and recent memories.
This allows you to distribute the workload across multiple LLMs. For example, if you have a conversation with 200,000
tokens resulting in about 200 memory chunks, you can assign these chunks to different LLMs. In a setup with three 8b
LLMs on separate computers, each LLM processes a chunk simultaneously, significantly reducing the processing time.

**Current Limitations:**

- Custom prompts are not yet supported for parallel processing but will be in the future. Currently, this feature is
  limited to processing memories and summaries.

---

### Presets

Presets in this project are highly customizable and not hardcoded. You can include any parameters you need in the JSON
file, allowing for flexibility and adaptability. If a new preset type is introduced tomorrow, you can simply add it to
the JSON file, and it will be sent over to the API without waiting for a new implementation.

#### Example Preset JSON

Here is an example of a preset JSON:

```json
{
  "truncation_length": 16384,
  "max_tokens": 3000,
  "temperature": 1,
  "top_p": 1
}
```

The current preset JSONs are a collection of parameters commonly used by SillyTavern and other front-end applications,
extracted directly from their payloads. Note that while most API endpoints are tolerant of additional parameters, some
like the OpenAI API will throw an error if you send parameters they do not know. Therefore, it's essential to include
only what is needed for those particular endpoints.

---

## Quick Troubleshooting Tips

### I don't see a memories file or summary file!

A) Make sure that those nodes exist in your workflow. Take a look at one of the
example workflows called FullCustomWorkflow-WithRecent-ChatSummary for an example.

B) Make sure the FOLDER exists. You can modify where these files are being
written to in your Users/username.json file.

### I'm not seeing a response coming in on the front end!

It could be a front end that doesn't work well with Wilmer, but the first
thing I'd check is that "streaming" matches on both sides. Both the front end
and Wilmer have to match for Stream being true or false. You can change this
in Wilmer in your Users/username.json file, and on SillyTavern it's in the
far left icon, around where Temperature is set.

### I'm getting an error that my LLM doesn't like some of the presets.

Some LLMs, like ChatGPT, don't accept presets that they don't recognize
(like dynamic temperature). You'll need to go through your workflows and
swap out all the presets with one that only has fields the API accepts.

### I want to update, but I don't want to lose all my stuff.

The public folder should be where all your settings are saved. I'd back
that folder up and move it between installations. This is still in heavy
development, so ultimately that folder may get broken at some point
because of changes, but I'll try my best not to.

### My routing is terrible/the outputs are awful/the LLM is really confused.

Check your prompt templates, check your prompts, etc. Small LLMs may have
a hard time with Wilmer, but a prompt template can make or break one, so
definitely be careful there.

### I keep getting out of memory/truncate length errors!

Wilmer currently has no token length checks to ensure that you aren't going
over the model's max length, so be careful there. If you have 200,000 tokens
of messages, there's nothing in Wilmer to stop you from trying to send all
200,000 to the LLM. That, of course, would cause it to fail.

### Getting some error about None type can't do something...

More than likely the LLM api either broke, didn't send back a response, or
send back something Wilmer didn't know what to do with. Or that something else
broke within Wilmer. Look at the output and you may see the cause.

### It looks like Wilmer is sending a prompt to the LLM, but nothing is happening.

Make sure that your endpoint's address and port are correct, and make sure that
you are using the right user. Everything may look fine, but you could have
the wrong user set as your current, in which case you're hitting a workflow
with endpoints that aren't set up. Wilmer just kind of stalls out if you try
to hit a link that doesn't exist, since the timeout is set for a really long
period of time due to some LLMs taking forever to respond.

---

## Contact

For feedback, requests, or just to say hi, you can reach me at:

WilmerAI.Project@gmail.com

---

## Third Party Libraries

WilmerAI imports five libraries within its requirements.txt, and imports the libraries via import statements; it does
not extend or modify the source of those libraries.

The libraries are:

* Flask : https://github.com/pallets/flask/
* requests: https://github.com/psf/requests/
* scikit-learn: https://github.com/scikit-learn/scikit-learn/
* urllib3: https://github.com/urllib3/urllib3/
* jinja2: https://github.com/pallets/jinja
* pillow: https://github.com/python-pillow/Pillow

Further information on their licensing can be found within the README of the ThirdParty-Licenses folder, as well as the
full text of each license and their NOTICE files, if applicable, with relevant last updated dates for each.

## Wilmer License and Copyright

    WilmerAI
    Copyright (C) 2025 Christopher Smith

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.