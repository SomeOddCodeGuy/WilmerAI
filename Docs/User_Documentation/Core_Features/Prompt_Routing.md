### **Feature Guide: WilmerAI's Prompt Routing Engine**

WilmerAI's **Prompt Routing** engine directs user requests to the most appropriate workflow based on the user's intent.
This allows for the use of specialized workflows tailored to specific tasks, rather than relying on a single, generic
model.

For example, the system can be configured to automatically route a coding question to a coding-optimized workflow, a
factual query to a research-enabled workflow, and a technical question to another specialized process.

-----

## How It Works: A Two-Part System

Prompt Routing is controlled by two configuration components: a **routing configuration file** that defines the possible
categories, and a **categorization workflow** that chooses one of those categories based on the user's prompt. The
system uses these two components together to route each incoming message.

The following example configuration for a user profile is defined in `assistant-multi-model.json`:

```json
  "routingConfig": "assistantMultiModelCategoriesConfig",
"categorizationWorkflow": "CustomCategorizationWorkflow",
```

### 1\. The Routing Configuration File

The first component is the routing configuration, specified in the `routingConfig` file. This file is a map that
connects category names to their descriptions and the workflow that should handle them.

Consider the example file, `assistantMultiModelCategoriesConfig.json`:

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

Each category in this file has two parts:

* **`description`**: This text is injected into the categorization workflow's prompt to instruct the LLM on the meaning
  of each category. Modifying these descriptions is the most effective way to improve routing accuracy.
* **`workflow`**: This is the name of the workflow that will be executed if this category is chosen by the
  categorization process.

### 2\. The Categorization Workflow

The second component is the **categorization workflow**. This is a standard WilmerAI workflow designed to analyze the
user's conversation and output a single word: the name of the chosen category. The system then uses this output to look
up the corresponding entry in the routing config file.

Here is the example `CustomCategorizationWorkflow.json`:

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

This workflow executes a two-step process:

1. **Analyze Intent:** The first node uses an LLM to summarize the user's latest message within the context of the
   recent conversation history.
2. **Select Category:** The second node takes that summary and uses an LLM to choose the best-fitting category from the
   list provided by the routing config file.

The final text output from this workflow is then matched against the category names in your routing config. If a match
is found, the corresponding workflow is run. If no clear match can be determined, the system will retry a few times
before falling back to a default workflow, named `_DefaultWorkflow`.

-----

## Dynamic Prompt Variables for Categorization

WilmerAI automatically generates several prompt variables from the routing configuration file to simplify the creation
of categorization workflows. These placeholders can be used in your prompts to dynamically insert categories and
descriptions.

* **`{category_colon_descriptions}`**
  Joins each category with its description, separated by a semicolon.

  > CODING: An appropriate response would fall within the category of writing...; TECHNICAL: An appropriate response
  would involve IT...

* **`{category_colon_descriptions_newline_bulletpoint}`**
  Lists each category and its description on a new line, prefixed with a dash.

  > - CODING: An appropriate response would fall within the category of writing...

  > - TECHNICAL: An appropriate response would involve IT...

  > - FACTUAL: An appropriate response requires encyclopedic knowledge of a factual person, place or thing...

* **`{categoriesSeparatedByOr}`**
  Provides a simple list of category names separated by "or".

  > CODING or TECHNICAL or FACTUAL

* **`{categoryNameBulletpoints}`**
  Provides a bulleted list of the category names.

  > - CODING

  > - TECHNICAL

  > - FACTUAL

* **`{category_list}`**
  Provides the raw list of category names.

* **`{category_descriptions}`**
  Provides the raw list of category descriptions.

-----

## The Next Step: Building Your Workflows

Once the routing logic is configured, the requests are handled by the specialized workflows you define. Each workflow
can be a unique chain of models, tools, and data sources tailored to a specific task.