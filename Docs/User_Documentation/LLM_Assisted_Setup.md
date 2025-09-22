### LLM Assisted Setup

The goal of this guide is to help you use an LLM to run through the quickstart guide for Wilmer. This has been updated
since the 2025-09 full installation YouTube video. So far I've tested it with GLM 4.5, and Qwen3 32b a3b. GLM did great,
but the Qwen3 30b struggled a bit. The size of the model is really a limiting factor on this, and it struggled with
some of the instructions.

In general, I recommend using something strong for this kind of task. If you have access to a proprietary AI, I'd
probably use that.

#### Files Needed

If you'd like to use an LLM to assist you in starting with wilmer, you may get best results by starting with supplying
it the following files:

* [`_Getting-Start_Wilmer-Api.md`](Setup/_Getting-Start_Wilmer-Api.md) (Quickstart guide)
* [`README.md`](README.md) (The main project overview)

#### Recommended Prompt

Below is the prompt that I would use if trying to use an LLM to assist. GLM 4.5 in Llama.cpp reports this as being ~3900
tokens

```text
I am trying to run a python project I got from github with the following documentation:

<project_doc>
... # Replace this with User_Documents/README.md
</project_doc>

and the following starter guide:
<starter_guide>
... # Replace this with starter guide
</starter_guide>

Can you please walk me step by step through what I need to do in order to accomplish this task, stopping at each step
until I am ready to move on? For each step, please specify what help document files you should be provided with, which are 
at the bottom of the provided starter guide. Please be straight forward and avoid flowery prose and overuse of emojis.

**IMPORTANT**: The user will not be looking at the file, only your output. Please be sure to accurately describe any
pertinent warnings, pro-tips, or other information that may help the user.
```

#### Files the LLM May (Should?) Ask For

* [`Setup/Configuration/Configuration_Files/Endpoint.md`](Setup/Configuration_Files/Endpoint.md)

* [`Setup/Configuration/Configuration_Files/ApiType.md`](Setup/Configuration_Files/ApiType.md)

* [
  `Setup/Configuration/Configuration_Files/PromptTemplates.md`](Setup/Configuration_Files/PromptTemplates.md)

* [`Setup/Configuration/Configuration_Files/User.md`](Setup/Configuration_Files/User.md)