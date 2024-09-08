# WilmerAI

## DISCLAIMER:

> This is a personal project that is under heavy development. It could, and likely does, contain bugs, incomplete code,
> or other unintended issues. As such, the software is provided as-is, without warranty of any kind.
>
> WilmerAI reflects the work of a single developer and the efforts of his personal time and resources; any views,
> methodologies, etc. found within are his own and should not reflect upon his employer.

## What is WilmerAI?

WilmerAI is a sophisticated middleware system designed to take incoming prompts and perform various tasks on them before
sending them to LLM APIs.
This work includes utilizing a Large Language Model (LLM) to categorize the prompt and route it to the appropriate
workflow
or processing a large context (200,000+ tokens) to generate a smaller, more manageable prompt suitable for most local
models.

### What Does WilmerAI Stand For?

WilmerAI stands for **"What If Language Models Expertly Routed All Inference?"**

## Key Features

- **Middleware Functionality:** WilmerAI sits between the interface you use to communicate with an LLM (such as
  SillyTavern, OpenWebUI, or even a Python program's terminal) and the backend API serving the LLMs. It can handle
  multiple backend LLMs simultaneously.

- **Flexible Connections:** Example setup: SillyTavern -> WilmerAI -> Koboldcpp. You can also connect one SillyTavern
  instance to WilmerAI, which can then connect to multiple LLM APIs (e.g., 4, 8, or 12).

- **API Endpoints:** It provides OpenAI API compatible `chat/Completions` and `v1/Completions` endpoints to connect to
  via your front end, and can connect to either type on the back end. This allows for complex configurations such as
  connecting SillyTavern to WilmerAI, and then having WilmerAI connected to multiple instances of KoboldCPP,
  Text-Generation-WebUI, ChatGPT API, and the Mistral API simultaneously.

- **Prompt Templates:** Supports prompt templates for `v1/Completions` API endpoints. WilmerAI also has its own prompt
  template for connections from a front end via `v1/Completions`. The template can be found in the "Docs" folder and is
  ready for upload to SillyTavern.

- **Multi-LLM Group Chats In SillyTavern:** There is an example character to show you how, but it is possible to use
  Wilmer to have a group chat in ST where every character is a different LLM, if you do desire (author personally does
  this. The example characters and two groups are subsets of larger groups that he uses).

## Some (Not So Pretty) Pictures to Help People Visualize What It Can Do

#### Single Assistant Routing to Multiple LLMs

![Single Assistant Routing to Multiple LLMs](Docs/Examples/Images/Wilmer_Example_Flow_1.png)

#### Silly Tavern Groupchat to Different LLMs

![Silly Tavern Groupchat to Different LLMs](Docs/Examples/Images/Wilmer_Example_Flow_2.png)

#### An Oversimplified Example Coding Workflow

![Oversimplified Example Coding Workflow](Docs/Examples/Images/Wilmer_Workflow_Example.png)

#### An Oversimplified Conversation/Roleplay Workflow

![Oversimplified Conversation/Roleplay Workflow](Docs/Examples/Images/Wilmer_Workflow_Example_2.png)

#### An Oversimplified Python Caller Workflow

![Oversimplified Python Caller Workflow](Docs/Examples/Images/Wilmer_Workflow_Example_3.png)

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
>
>While the author is doing his best to make something useful and high quality, this is an ambitious solo project and is
> bound to have its problems (especially since the author is not natively a Python developer, and relied heavily on AI
> to
> help him get this far). He is slowly figuring it out, though.

## Connecting to Wilmer

Wilmer exposes both an OpenAI v1/Completions and chat/Completions endpoint, making it compatible with most front ends.
While I have primarily used this with SillyTavern, it might also work with Open-WebUI.

### Connecting in SillyTavern

#### Text Completion (Author's preferred method)

To connect as a Text Completion in SillyTavern, follow these steps (the below screenshot is from SillyTavern):

![Text Completion Settings](Docs/Examples/Images/ST_text_completion_settings.png)

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

#### Chat Completions

To connect as Chat Completions in SillyTavern, follow these steps (the below screenshot is from SillyTavern):

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
    > had pretty decent results for me, and I'm hoping it will for you as well.
>
>
> * C) By default, all the user files are set to turn on streaming responses. You either need to enable
    this in your front end that is calling Wilmer so that both match, or you need to go into Users/username.json
    and set Stream to "false". If you have a mismatch, where the front end does/does not expect streaming and your
    > wilmer expects the opposite, nothing will likely show on the front end.

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

> **NOTE:** When running either the bat file, the sh file or the python file, all three now accept "--ConfigDirectory"
> and "--User" arguments. So, for example: "bash run_macos.sh --ConfigDirectory "/users/socg/Public/configs" --User
"single-model-assistant". This means that you can start up multiple instances of wilmer at once with a single install
> folder,
> and that you don't have to update the current-user anymore if you dont want to. Specifying --User will ignore
> current-user.json.

### Step 2 Fast Route: Use Pre-made Users

Within the Public/Configs you will find a series of folders containing json files. The two that you are
most interested in are the `Endpoints` folder and the `Users` folder.

**NOTE:** The Factual workflow nodes of the `assistant-singlemode`, `assistant-multi-model`
and `group-chat-example` users will attempt to utilize the
[OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi)
project to pull full wikipedia articles to RAG against. If you don't have this API, the workflow
should not have any issues, but I personally use this API to help improve the factual responses I get.
You can specify the IP address to your API in the user json if your choice.

First, choose which template user you'd like to use:

* **assistant-single-model**: This template is for a single small model being used on all nodes. The endpoint used here
  is
  `SmallModelEndpoint`. This also has routes for many different category types and uses appropriate presets for each
  node. If you're wondering why there are routes for different categories when there is only 1 model: it's so that you
  can
  give each category their own presets, and also so that you can make custom workflows for them. Maybe you want the
  coder to do multiple iterations to check itself, or the reasoning to think through things in multiple steps.


* **assistant-multi-model**: This template is for using many models in tandem: Looking at the endpoints for
  this user, you can see that every category has its own endpoint. There is absolutely nothing stopping you from
  re-using the same api for multiple of them. For example, you might use Llama 3.1 70b for Coding, math, and reasoning,
  and Command-R 35b 08-2024 for categorization, conversation, and factual. Don't feel like you NEED 10 different models.
  This is simply to allow you to bring that many if you want. This user uses appropriate presets for each node in the
  workflows.


* **convo-roleplay-single-model**: This user uses a single model with a custom workflow that is good for
  conversations,
  and should be good for roleplay (awaiting feedback to tweak if needed). This bypasses all routing.


* **convo-roleplay-dual-model**: This user uses two models with a custom workflow that is good for conversations,
  and should be good for roleplay (awaiting feedback to tweak if needed). This bypasses all routing. **NOTE**: This
  workflow works best if you have 2 computers that can run LLMs. With the current setup for this user, when you send a
  message
  to Wilmer, the responder model (computer 1) will respond to you. Then the workflow will apply a "workflow lock" at
  that
  point. The memory/chat summary model (computer 2) will then begin updating the memories and summary of the
  conversation so far, which is passed to the responder to help it remember stuff. If you were to send another prompt
  while the memories are being written, the responder (Computer 1) will grab whatever existing summary exists and
  go ahead and respond to you. The workflow lock will stop you from re-entering the new memories section. What this
  means is that you can continue talking to your responder model while new memories are being written. This is a HUGE
  performance boost. I've tried it out, and for me the response times were amazing. Without this, I get responses in 30
  seconds 3-5 times, and then suddenly have a 2 minute wait to generate memories. With this, every message is 30
  seconds, every time, on Llama 3.1 70b on my Mac Studio.


* **group-chat-example**: This user is an example of my own personal group chats. This is a subset of a larger group,
  but
  but the characters included and the groups included are actual characters and actual groups that I use. The dev team
  characters have only 1 node per workflow: they simply respond to you. The advisory group characters have 2 nodes
  per workflow: first node generates a response, and the second node enforces the character's "persona". The group
  chat personas help a lot to vary up the responses you get, even if you use only 1 model. However, I aim to use
  different models for every character (but re-using models between groups. So, for example, I have a Llama 3.1 70b
  model character in each group)

Once you have selected the user that you want to use, there are a couple of steps to perform:

1) Update the endpoints for your user under Public/Configs/Endpoints. The example characters are sorted into folders
   for each. The user's endpoint folder is specified at the bottom of their user.json file. You will want to fill in
   every endpoint
   appropriately for the LLMs you are using. You can find some example endpoints under the examples folder.
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

#### Endpoints

These configuration files represent the LLM API endpoints you are connected to. For example, the following JSON
file, `SmallModelEndpoint.json`, defines an endpoint:

```json
{
  "modelNameForDisplayOnly": "Small model for all tasks",
  "endpoint": "http://127.0.0.1:5000",
  "apiTypeConfigFileName": "KoboldCpp",
  "maxContextTokenSize": 8192,
  "modelNameToSendToAPI": "",
  "promptTemplate": "chatml",
  "addGenerationPrompt": true
}
```

- **endpoint**: The address of the LLM API that you are connecting to. Must be an openAI compatible API of either
  text Completions or Chat Completions type (if you're unsure- that's the vast majority of APIs, so this will
  probably work with whatever you're trying)
- **apiTypeConfigFileName**: The exact name of the json file from the ApiTypes folder that specifies what type
  of API this is, minus the ".json" extension. "Open-AI-API" will probably work for most cloud services.
- **maxContextTokenSize**: Specifies the max token size that your endpoint can accept
- **modelNameToSendToAPI**: Specifies what model name to send to the API. For cloud services, this can be important.
  For example, OpenAI may expected "gpt-3.5-turbo" here, or something like that. For local AI running in Kobold,
  text-generation-webui, etc, this is mostly unused. (Ollama may use it, though)
- **promptTemplate**: The exact json file name of the prompt template to use, minus the ".json" extension. These
  can be found in the PromptTemplates folder.
- **addGenerationPrompt**: This boolean is for Text Completion endpoints to specify whether the model expects a
  final "assistant" tag at the very end. Not all models do. If you're unsure about this, just set it to
  "false"

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

- **type**: Can be either "openAIV1Completion" or "openAIChatCompletion". Use "openAIV1Completion" for KoboldCpp and "
  openAIChatCompletion" for OpenAI's API.
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
  node within workflows
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
  "endpointConfigsSubDirectory": "assistant-single-model"
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
  when using `discussionId`.
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
- **offlineWikiApiHost**: IP of the computer running the API
- **offlineWikiApiPort**: Port for your wiki API. Unless you specifically change this, it's already good in all the
  example user configs.
- **endpointConfigsSubDirectory**: Name of the subfolder in Endpoints where your endpoint jsons will live.

#### Users Folder, _current-user.json File

Next, update the `_current-user.json` file specify what user you want to use. Match the name of the new user JSON file,
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
* You should have ensured your new user json file has the correct routing config specified in it
* You should have a folder with your user's name in the Workflows folder.
    * This folder should contain a json matching every workflow from your user folder
    * This folder should contain a json matching every workflow from your Routing config
        * If you're missing a workflow, Wilmer will crash.

## Understanding Workflows

### Setting up Workflows

Workflows in this project are modified and controlled in the `Public/Workflows` folder, within your user's specific
workflows folder. For example, if your user is named `socg` and you have a `socg.json` file in the `Users` folder, then
within workflows you should have a `Workflows/socg` folder.

### Example Workflow JSON

Here is an example of what a workflow JSON might look like:

```json
[
  {
    "title": "Coding Agent",
    "agentName": "Coder Agent One",
    "systemPrompt": "You are an exceptionally powerful and intelligent technical AI that is currently in a role play with a user in an online chat.\nThe instructions for the roleplay can be found below:\n[\n{chat_system_prompt}\n]\nPlease continue the conversation below. Please be a good team player. This means working together towards a common goal, and does not always include being overly polite or agreeable. Disagreement when the other user is wrong can help foster growth in everyone, so please always speak your mind and critically review your peers. Failure to correct someone who is wrong could result in the team's work being a failure.",
    "prompt": "",
    "lastMessagesToSendInsteadOfPrompt": 6,
    "endpointName": "SocgMacStudioPort5002",
    "preset": "Coding",
    "maxResponseSizeInTokens": 500,
    "addUserTurnTemplate": false
  },
  {
    "title": "Reviewing Agent",
    "agentName": "Code Review Agent Two",
    "systemPrompt": "You are an exceptionally powerful and intelligent technical AI that is currently in a role play with a user in an online chat.",
    "prompt": "You are in an online conversation with a user. The last five messages can be found here:\n[\n{chat_user_prompt_last_five}\n]\nYou have already considered this request quietly to yourself within your own inner thoughts, and come up with a possible answer. The answer can be found here:\n[\n{agent1Output}\n]\nPlease critically review the response, reconsidering your initial choices, and ensure that it is accurate, complete, and fulfills all requirements of the user's request.\n\nOnce you have finished reconsidering your answer, please respond to the user with the correct and complete answer.\n\nIMPORTANT: Do not mention your inner thoughts or make any mention of reviewing a solution. The user cannot see the answer above, and any mention of it would confuse the user. Respond to the user with a complete answer as if it were the first time you were answering it.",
    "endpointName": "SocgMacStudioPort5002",
    "preset": "Coding",
    "maxResponseSizeInTokens": 1000,
    "addUserTurnTemplate": true
  }
]
```

### Workflow Nodes

The above workflow is made up of conversation nodes. Both nodes do one simple thing: send a message to the LLM specified
at the endpoint.

#### Node Properties

- **title**: This is for your use only and may show up in the console when running to help with debugging.
- **agentName**: Similar to `title`. It's helpful to name these ending in "One", "Two", etc., to keep track of the agent
  output. The first node's output is saved to `{agent1Output}`, the second to `{agent2Output}`, and so on.
- **systemPrompt**: The system prompt to send to the LLM API.
- **prompt**: The prompt to send. If left blank, either the last five messages from your conversation will be sent, or
  however many you specify.
- **lastMessagesToSendInsteadOfPrompt**: Specify how many messages to send to the LLM if "prompt" is left as an empty
  string.
- **endpointName**: The LLM API endpoint to send the prompt to. This should match a JSON file name from the `Endpoints`
  folder, without the `.json` extension.
- **preset**: The preset to send to the API. Truncate length and max tokens to send come from this. This should match a
  JSON file name from the `Presets` folder, without the `.json` extension.
- **maxResponseSizeInTokens**: Specifies the maximum number of tokens you want the LLM to send back to you as a
  response.
  This can be set per node, in case you want some nodes to respond with only 100 tokens and others to respond with 3000.
- **addUserTurnTemplate**: Whether to wrap the prompt being sent to the LLM within a user turn template. If you send the
  last few messages, set this as `false` (see first example node above). If you send a prompt, set this as `true` (see
  second example node above).

### Variables in Prompts

You can use several variables within these prompts. These will be appropriately replaced at runtime:

- `{chat_user_prompt_last_one}`: The last message in the conversation, without prompt template tags wrapping the
  message.
    - Variables for last "one", "two", "three", "four", "five", "ten", and "twenty" messages are available.
    - Typically used in prompts.
- `{templated_user_prompt_last_one}`: The last message in the conversation, wrapped in the appropriate user/assistant
  prompt template tags.
    - Variables for last "one", "two", "three", "four", "five", "ten", and "twenty" messages are available.
    - Rarely needed.
- `{chat_system_prompt}`: The system prompt sent from the front end. Often contains character card and other important
  info.
    - Commonly used.
- `{templated_system_prompt}`: The system prompt from the front end, wrapped in the appropriate system prompt template
  tag.
    - Used if the workflow system prompt is just the system prompt.
- `{agent#Output}`: `#` is replaced with the number you want. Every node generates an agent output. The first node is
  always 1, and each subsequent node increments by 1. For example, `{agent1Output}` for the first node, `{agent2Output}`
  for the second, etc.
    - Accessible in any node after they've run.
- `{category_colon_descriptions}`: Pulls the categories and descriptions from your `Routing` JSON file.
    - Example: "CODING: Any request which requires a code snippet as a response; FACTUAL: Requests that require factual
      information or data; CONVERSATIONAL: Casual conversation or non-specific inquiries".
- `{categoriesSeparatedByOr}`: Pulls the category names, separated by "OR".
    - Example: "CODING OR FACTUAL OR CONVERSATION".
- `[TextChunk]`: A special variable unique to the parallel processor, likely not used often.

### Other Types of Nodes

#### Recent/Quality Memory Node

This node will group together the messages that you send the LLM into small chunks, and then use an LLM to summarize
them. This triggers a call to the "RecentMemoryToolWorkflow", and then will save the output of that to a memory file.
This node will look for `[DiscussionId]#####[/DiscussionId]` anywhere in the conversation, either in the system prompt
or the messages (where #### is any number. So, for example, `[DiscussionId]123456[/DiscussionId]`. The file will be
written as the `DiscussionId + _memories.json`; so `123456_memories.json`, in our example. I recommend not putting it in
the system prompt, as then the memory will be shared between all chats. Once this file is created, this node will do a
keyword search against the memories for anything related to the current conversation. So the result may be several
summarized memory chunks loosely related to what's being talked about.

```json
{
  "title": "Checking AI's long term memory about this topic",
  "agentName": "QualityMemoryAgent",
  "type": "QualityMemory"
}
```

#### Chat Summary Node

This node will also generate the same recent memories file above, if it doesn't exist already, and then will take all
the memories and summarize them into a single large summary. This summary is saved in `discussionId_chatsummary.json`.
So `123456_chatsummary.json`, in our above example. If a chat summary already exists and was recently updated, it will
simply use the one that already exists. If one exists and it hasnt been updated in a while, it will update the summary.

```json
{
  "title": "Checking AI's recent memory about this topic",
  "agentName": "Chat Summary",
  "type": "FullChatSummary",
  "isManualConfig": false
}
```

* isManualConfig is supposed to tell the chatSummary to look for a summary file but not write to it, so that the user
  can write their own summaries. However, I think this field is actually bugged and does nothing. Just leave this false
  for now.

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

```json
  {
  "title": "Querying the offline wikipedia api",
  "agentName": "Wikipedia Search Api Agent Three",
  "promptToSearch": "{agent1Output}",
  "type": "OfflineWikiApiFullArticle"
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

## Understanding Memories

### Quality Memory (utilizing "Recent Memories")

The "Recent Memories" function is designed to enhance your conversation experience by chunking and summarizing your
messages, writing them to a specified text file. This feature continuously searches these memories via keywords relevant
to your current topic. After every few messages, it adds a new memory to ensure the conversation stays contextually up
to date.

To enable this, include a tag in your conversation: `[DiscussionId]#######[/DiscussionId]`, where `######` is any
numerical value. For example `[DiscussionId]123456[/DiscussionId]`. You can insert this tag anywhere in the system
prompt or prompt; Wilmer should remove the tag before sending prompts to your LLM. Without this tag, the function
defaults to searching the last N number of messages instead.

**Note:** In SillyTavern, placing the tag in the character card will cause every conversation with that character to
share the same memories, leading to confusion. I recommend putting it somewhere in the conversation or the author's
note.

### Chat Summary

The "Chat Summary" function builds upon the "Recent Memories" by summarizing the entire conversation up to the current
point. It updates the summary every time new memories are added. Similar to "Recent Memories," this feature requires
the `[DiscussionId]#######[/DiscussionId]` tag to function correctly.

### Resetting Memories and Summary

At any point, you can simply delete the files and they will get rebuilt, if applicable. I recommend this over modifying
them directly. (Note that if you delete the Memories file, you should also remove the Summary file, but you can safely
delete the Summary by itself.)

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

Further information on their licensing can be found within the README of the ThirdParty-Licenses folder, as well as the
full text of each license and their NOTICE files, if applicable, with relevant last updated dates for each.

## Wilmer License and Copyright

    WilmerAI
    Copyright (C) 2024 Christopher Smith

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
