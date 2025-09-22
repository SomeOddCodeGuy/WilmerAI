### **Feature Guide: WilmerAI's Adaptable LLM Connector**

*Note: WilmerAI exposes a **Universal API Gateway** that allows you to connect your existing applications as if you were
talking directly to OpenAI or Ollama. This document explains the backend mechanism for connecting to and orchestrating
various Large Language Models.*

WilmerAI can act as a **bridge** to most Large Language Model (LLM) backends. You are not locked into a single provider
or API. Whether you're running a model locally with Ollama, using a cloud service like OpenAI, or a custom KoboldCpp
setup, WilmerAI can connect to it.

This guide explains how this system works and how you can use it to build flexible workflows.

-----

## How Backend Connections Work: The Three Core Components

WilmerAI's backend connectivity is managed by three types of configuration files. They define the **Where**, the **How
**, and the **What** of an LLM connection.

#### 1\. Endpoints: The "Where"

An **Endpoint** file specifies the network address of an LLM server and assigns it a name. Each file in
`Public/Configs/Endpoints/` represents one LLM you can connect to.

The two most important fields in an Endpoint file are:

* `"endpoint"`: The URL of the LLM server (e.g., `"http://localhost:11434"` for a local Ollama instance).
* `"apiTypeConfigFileName"`: The name of the API Type file that tells WilmerAI how to format requests for this endpoint.

#### 2\. API Types: The "How"

An **API Type** file functions as a driver for an LLM's API. Different backends have different schemas; for example,
OpenAI uses `"max_tokens"` to limit response length, while Ollama uses `"num_predict"`.

The API Type file maps these different property names to a common internal standard. This allows WilmerAI to support
Ollama, OpenAI, KoboldCpp, and more without changing its core code. You tell your Endpoint to use the correct API Type
file, and WilmerAI handles the translation.

Support for a new LLM backend can be added by creating a new API Type file that describes its schema.

#### 3\. Presets: The "What"

A **Preset** file defines the generation parameters for an LLM. This includes settings like `temperature`, `top_p`, and
`stop_sequence`.

These are kept separate from Endpoints so you can reuse the same preset with different models or have multiple presets (
e.g., "creative," "analytical," "short\_summary") for a single model.

-----

## Per-Node Connections

A workflow is a sequence of steps, or "nodes." **Each node in a workflow can connect to a different Endpoint.**

This allows you to choose the most appropriate model for each task in a workflow.

#### Practical Example: A RAG Agent

Consider a RAG (Retrieval-Augmented Generation) agent that answers questions based on a set of documents.

1. **Node 1: Keyword Extraction:** The user asks a complex question. The first node's job is to extract keywords from
   this question to search a database. This is a simple task that can be assigned to a **small, fast, local model**
   running via Ollama for a quick result.

    * **Endpoint:** `Ollama-Llama3-Local`

2. **Node 2: Final Answer Generation:** The keywords are used to retrieve relevant documents. The second node's job is
   to read the original question and the retrieved documents to generate a comprehensive answer. This is a complex task
   that can be assigned to a **more powerful model** like GPT-4o.

    * **Endpoint:** `OpenAI-GPT4o-Cloud`

In this workflow, two different LLMs from two different providers are used in a single request, allowing you to optimize
for both speed and cost.

-----

## Putting It All Together: A Quick Walkthrough

To connect a model in your workflow:

1. **Define your Endpoint:** Create a JSON file in `Public/Configs/Endpoints/` (e.g., `MyLocalModel.json`). Inside,
   specify the server `endpoint` URL and the `apiTypeConfigFileName` (e.g., `"Ollama"`).
2. **Reference it in your Workflow:** In your workflow's JSON file, find the node you want to configure.
3. **Set the `endpointName`:** Add the `"endpointName"` property to the node, and set its value to the name of your
   Endpoint file (without the `.json`).

<!-- end list -->

```json
{
  "nodes": [
    {
      "title": "Respond to User",
      "type": "Standard",
      "prompt": "Hello! How can I help you today?",
      "endpointName": "MyLocalModel",
      // This tells the node to use your specific endpoint
      "presetName": "Creative",
      "returnToUser": true
    }
  ]
}
```

The node is now configured to send its request to the LLM defined in `MyLocalModel.json`, using the API rules from the
`Ollama` API Type and the generation settings from the `Creative` preset.