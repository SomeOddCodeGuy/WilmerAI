## Quick Guide to Understanding Prompt Routing in WilmerAI

Prompt routing is primarily controlled by 2 pieces

* A categorization workflow, specified in your user config
* A routing file, also specified in your user config.

Let's consider an example user: [assistant-multi-model](../../Public/Configs/Users/assistant-multi-model.json).

Looking at this user, we see things:

```
  "routingConfig": "assistantMultiModelCategoriesConfig",
  "categorizationWorkflow": "CustomCategorizationWorkflow",
```

First, lets look at [the routing config](../../Public/Configs/Routing/assistantMultiModelCategoriesConfig.json):

```
{
  "CODING": {
    "description": "An appropriate response would fall within the category of writing, editing or answering questions about code or other software development related topics (such as SQL queries).",
    "workflow": "CodingWorkflow-LargeModel-Centric"
  },
  "TECHNICAL": {
    "description": "An appropriate response would involve IT or technical related discussion that does not fall within the definition of 'CODING'",
    "workflow": "Technical-Workflow"
  },
  "FACTUAL": {
    "description": "An appropriate response would require encyclopedic knowledge of a topic, and would benefit from direct access to wikipedia articles",
    "workflow": "Factual-Wiki-Workflow"
  },
  ...
  ...
```

You can see that the routing config is made up of 2 pieces:

* Description: This is sent to the LLM alongside the category to tell it what fits into that category. This isn't just
  for display; this is part of the prompt, so tweaking these descriptions can improve your routing results
* workflow: the name of the workflow, in your user's workflow folder, that will be called for this route.

If we then take a look at the categorization workflow for this user, we see this (as of 2024-11-30)
:

```json
[
  {
    "title": "Analyzing the conversation context",
    "agentName": "Conversation Analyzer Agent One",
    "systemPrompt": "When given an ongoing conversation, review the most recent messages and expertly outline exactly what the most recent speaker is asking for or saying. Please make use of previous messages in the conversation to confirm the context of the most recent speaker's message. Make sure to specify whether the speaker is seeking a specific answer, making a specific request, playing around, or just engaging in idle conversation.",
    "prompt": "Please consider the below messages:\n[\n{chat_user_prompt_last_ten}\n]\nConsidering the full context of the messages given, please analyze and report the exact context of the last speaker's messages. Do not simply assume that it is discussing the most recent messages; consider the entire context that has been provided and think deeply about what the speaker might really be saying.\n\nIf the final message is a prompt for the most recent speaker to speak again, this is a 'Continue' situation where the next message continue where the previous message left off. This is a very important piece of information that should be noted\n\nIMPORTANT: Please be sure to consider if the last speaker is simply responding with appreciation, is changing the subject or is concluding a topic. The result of this request will decide what tools will be utilized to generate a response, and failure to appropriately not the end of a conversation topic could result in the wrong tool being used.",
    "lastMessagesToSendInsteadOfPrompt": 5,
    "endpointName": "Assistant-Multi-Model-Categorizer-Endpoint",
    "preset": "Categorizer_Preset",
    "maxResponseSizeInTokens": 300,
    "addUserTurnTemplate": true
  },
  {
    "title": "Determining category of prompt",
    "agentName": "Categorization Agent Two",
    "systemPrompt": "When given a message and a series of categories to choose from, always respond with only a single word: the expected category. Do not include any other words than the single appropriate category that was chosen.\nIMPORTANT: When categorizing, always consider whether a topic has concluded or the subject has been changed, and adjust the category accordingly.",
    "prompt": "A user is currently in an online conversation, and has sent a new message. The intent and context of the message has been described below:\n[\n{agent1Output}\n]\nPlease categorize the user's message into one of the following categories: {category_colon_descriptions}. Return only one word for the response.\n\nPlease respond with one of the following: {categoriesSeparatedByOr}.",
    "endpointName": "Assistant-Multi-Model-Categorizer-Endpoint",
    "preset": "Categorizer_Preset",
    "maxResponseSizeInTokens": 300,
    "addUserTurnTemplate": true
  }
]
```

This workflow does 2 things:

* First, it has the LLM summarize exactly what the intent of the user is. What are they saying and what are they asking
  for?
* Then, it asks the LLM to specify which of the categories we gave it the output of node 1 would fall into.

You can see `{category_colon_descriptions}` in the prompt; that would return something like

> CODING: An appropriate response would fall within the category of writing, editing or answering questions about code
> or other software development related topics (such as SQL queries).

for each of the categories in our file.

We also see `{categoriesSeparatedByOr}`. That would output something like:

> CODING or TECHNICAL or FACTUAL...

For each of our categories.

This is a regular workflow, so if you wanted to update it to be 10 different nodes, you could. The output of the
final node will be used by Wilmer as the category.

In the event that no category can be found, the default workflow will be run.