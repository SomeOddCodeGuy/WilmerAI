## Quick Guide to Prompt Routing in WilmerAI

Prompt routing is the brain behind WilmerAI's ability to use the right tool for the right job. It's controlled by two
key pieces you can configure:

* A **categorization workflow**, specified in your user config. This workflow's job is to figure out what the user is
  talking about.
* A **routing configuration file**, also specified in your user config. This file acts as a map, telling the system
  which specialized workflow to run based on the category that was chosen.

Let's consider an example user: `assistant-multi-model.json`.

Looking at this user's config, we see these two important lines:

```json
  "routingConfig": "assistantMultiModelCategoriesConfig",
"categorizationWorkflow": "CustomCategorizationWorkflow",
```

-----

### The Routing Config File

First, let's look at the routing config, `assistantMultiModelCategoriesConfig.json`:

```json
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
  }
}
```

This file is a simple map made up of categories (like "CODING", "TECHNICAL", etc.). Each category has two parts:

* **`description`**: This text is sent to the LLM during the categorization step. It's not just for display; it's a
  critical part of the prompt that teaches the LLM what each category means. Tweaking these descriptions is the best way
  to improve your routing results.
* **`workflow`**: This is the name of the workflow that will be run if this category is chosen.

-----

### The Categorization Workflow

Next is the categorization workflow itself. This is a standard workflow, but its purpose is to analyze the user's
conversation and output a single word: the name of the category it chose. The system will then use that word to find a
match in your routing config.

Here's the example `CustomCategorizationWorkflow.json`:

```json
[
  {
    "title": "Analyzing the conversation context",
    "agentName": "Conversation Analyzer Agent One",
    "systemPrompt": "When given an ongoing conversation, review the most recent messages and expertly outline exactly what the most recent speaker is asking for or saying...",
    "prompt": "Please consider the below messages:\n[\n{chat_user_prompt_last_ten}\n]\n...please analyze and report the exact context of the last speaker's messages...",
    "endpointName": "Assistant-Multi-Model-Categorizer-Endpoint"
  },
  {
    "title": "Determining category of prompt",
    "agentName": "Categorization Agent Two",
    "systemPrompt": "When given a message and a series of categories to choose from, always respond with only a single word: the expected category...",
    "prompt": "A user is currently in an online conversation, and has sent a new message. The intent and context of the message has been described below:\n[\n{agent1Output}\n]\nPlease categorize the user's message into one of the following categories: {category_colon_descriptions}. Return only one word for the response.\n\nPlease respond with one of the following: {categoriesSeparatedByOr}.",
    "endpointName": "Assistant-Multi-Model-Categorizer-Endpoint"
  }
]
```

This workflow does two things:

1. First, it has the LLM summarize the intent of the user's latest message based on the conversation history.
2. Then, it feeds that summary into a second node, asking the LLM to pick the best category from a list.

The final output of this workflow is what matters. The system takes the text from the last node, cleans it up, and tries
to match it to a key in your routing config. If it can't get a clear answer, it will even retry a few times before
giving up.

If no category can be matched, a default workflow (`_DefaultWorkflow`) will be run instead.

-----

### Available Prompt Variables

When building your categorization workflow, the system automatically makes several variables available based on your
routing config file. You can use these placeholders in your prompts to dynamically insert your categories and
descriptions.

Here are all the available variables:

* **`{category_colon_descriptions}`**
  This joins each category with its description, separated by a semicolon.

  > CODING: An appropriate response would fall within the category of writing...; TECHNICAL: An appropriate response
  would involve IT...

* **`{category_colon_descriptions_newline_bulletpoint}`**
  This lists each category and its description on a new line with a dash.

  > - CODING: An appropriate response would fall within the category of writing...
  >   - TECHNICAL: An appropriate response would involve IT...

* **`{categoriesSeparatedByOr}`**
  This gives a simple list of category names.

  > CODING or TECHNICAL or FACTUAL

* **`{categoryNameBulletpoints}`**
  This gives a bulleted list of just the category names.

  > - CODING
  >   - TECHNICAL
  >   - FACTUAL

* **`{category_list}`**
  This provides the raw list of category names (less useful for prompts, but available).

* **`{category_descriptions}`**
  This provides the raw list of descriptions (less useful for prompts, but available).