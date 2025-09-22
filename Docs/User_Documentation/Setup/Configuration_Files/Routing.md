### **`Routing` Configuration Files**

The routing configuration files, located in `Public/Configs/Routing/`, define how WilmerAI directs incoming user prompts
to different processing workflows. Each JSON file maps prompt categories (e.g., "Coding", "Factual") to a specific
workflow file.

When a request is received and the `customWorkflowOverride` setting in the user's configuration is `false`, the system
first runs a "categorization workflow." This initial workflow uses an LLM to analyze the request and assign it to one of
the categories defined in the routing file. The system then executes the workflow associated with that category.

This process allows different types of prompts to be handled by specialized workflows. A user's active routing file is
specified by the `routingConfig` field in their `Public/Configs/Users/<username>.json` file.

-----

#### **File Structure**

A routing configuration file is a single JSON object where each top-level key is a unique string representing a
category. The value for each key is a nested object containing the route's details.

##### `Category Key` (e.g., "CODING")

* **Description**: The unique identifier for the route. This key serves as the **target output** for the categorization
  LLM. The system's categorization service attempts to match the LLM's response to one of these keys. By convention,
  keys are in `UPPERCASE_SNAKE_CASE` for reliable matching.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: `"FACTUAL"`

-----

#### **Category Object Fields**

For each `Category Key`, the value is a nested JSON object containing the following two fields.

##### `description`

* **Description**: A detailed explanation of what kind of prompt should be assigned to this category. This field is *
  *critical for accurate routing**. The `PromptCategorizationService` combines the **Category Key** and this *
  *description** into a single string (e.g.,
  `"CODING: Any request which requires generating or analyzing a code snippet..."`) and injects it into the prompt that
  is sent to the categorization LLM.
* **Data Type**: `string`
* **Required**: Yes

##### `workflow`

* **Description**: The name of the workflow file to execute if this category is selected. The system will look for this
  file in the user's workflow directory (`Public/Configs/Workflows/<username>/`). The **`.json` extension must be
  omitted**.
* **Data Type**: `string`
* **Required**: Yes
* **Example**: A value of `"FactualWorkflow-With-RAG"` instructs the system to run the
  `Public/Configs/Workflows/<username>/FactualWorkflow-With-RAG.json` file.

-----

#### **Example Routing File**

Filename: `assistantSingleModelCategoriesConfig.json`

```json
{
  // The unique identifier for the route. This is the target output
  // for the categorization LLM.
  "CODING": {
    // This text is injected into the categorization prompt to help the LLM
    // make an accurate choice.
    "description": "Any request which requires generating or analyzing a code snippet, discussing algorithms, or explaining programming concepts.",
    // The workflow file (without .json) to execute if this category is chosen.
    "workflow": "CodingWorkflow-LargeModel-Centric"
  },
  "FACTUAL": {
    "description": "Requests that require verifiable, factual information, data lookups, or answers from a knowledge base. This includes history, science, and definitions.",
    "workflow": "FactualWorkflow-With-RAG"
  },
  "CONVERSATIONAL": {
    "description": "Casual conversation, general inquiries, brainstorming, creative writing, or any request that does not fall into other specific categories.",
    "workflow": "DefaultConversationalWorkflow"
  }
}
```

-----

#### **The Routing Process**

1. **Initiation**: A request is received. The system checks that the user's `customWorkflowOverride` setting is `false`.
2. **Loading**: The `PromptCategorizationService` reads the routing file specified in the user's `routingConfig`
   setting.
3. **Prompt Assembly**: The service constructs a prompt for the categorization LLM. This prompt includes the user's
   message history and the list of all categories and their descriptions from the routing file.
4. **Categorization**: The system executes the workflow specified in the user's `categorizationWorkflow` setting. This
   workflow calls an LLM with the assembled prompt to get a one-word category back.
5. **Matching**: The `PromptCategorizationService` receives the category name (e.g., `"CODING"`) and matches it to a
   `Category Key` in the routing file.
6. **Execution**: The service retrieves the `workflow` value from the matched category (e.g.,
   `"CodingWorkflow-LargeModel-Centric"`) and executes that final workflow to generate the response.
7. **Fallback**: If the categorization LLM's output does not match any defined `Category Key`, the system executes the
   `_DefaultWorkflow` as a fallback.