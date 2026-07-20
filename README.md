# WilmerAI

*"What If Language Models Expertly Routed All Inference?"*

## DISCLAIMER:

> This project is still under development. The software is provided as-is, without warranty of any kind.
>
> This project and any expressed views, methodologies, etc., found within are the result of contributions by the
> maintainer and any contributors in their free time and on their personal hardware, and should not reflect upon
> any of their employers.
>
> [The maintainer of this project, SomeOddCodeGuy, is not doing any Contract, Freelance, or Collaboration
> work.](https://github.com/SomeOddCodeGuy#disclaimer)

---

## What is WilmerAI?

WilmerAI is an application designed for advanced semantic prompt routing and complex task orchestration. It
originated from the need for a router that could understand the full context of a conversation, rather than just the
most recent message.

Unlike simple routers that might categorize a prompt based on a single keyword, WilmerAI's routing system can analyze
the entire conversation history. This allows it to understand the true intent behind a query like "What do you think it
means?", recognizing it as historical query if that statement was preceded by a discussion about the Rosetta Stone,
rather than merely conversational.

This contextual understanding is made possible by its core: a **node-based workflow engine**. Like the rest of Wilmer,
the routing is a workflow, categorizing through a sequence of steps, or "nodes", defined in a JSON file.
The route chosen kicks off another specialized workflow, which can call more workflows from there. Each node can
orchestrate different LLMs, call external tools, run custom scripts, call other workflows, and many other things.

To the client application, this entire multi-step process appears as a standard API call, enabling advanced backend
logic without requiring changes to your existing front-end tools.

---

## Working with Workflows

### Semi-Autonomous Workflows Allow You Determine What Tools and When

The below shows Open WebUI connected to 2 instances of Wilmer (recorded before multi-user support was added; a single
instance can now serve multiple users). The first instance just hits Mistral Small 3 24b directly, and then the second
instance makes a call to the [Offline Wikipedia API](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi) before
making the call to the same model.

![No-RAG vs RAG](Doc_Resources/Media/Gifs/Search-Gif.gif)
*Click the image to play gif if it doesn't start automatically*

### Iterative LLM Calls To Improve Performance

A zero-shot to an LLM may not give great results, but follow-up questions will often improve them. If you
regularly perform
[the same follow-up questions when doing tasks like software development](https://www.someoddcodeguy.dev/my-personal-guide-for-developing-software-with-ai-assistance/),
creating a workflow to automate those steps can have great results.

### Distributed LLMs

With workflows, you can have as many LLMs available to work together in a single call as you have computers to support.
For example, if you have old machines lying around that can run 3-8b models? You can put them to use as worker LLMs in
various nodes. The more LLM APIs that you have available to you, either on your own home hardware or via proprietary
APIs, the more your workflow network can do. A single prompt to Wilmer could reach out to 5+ computers,
including proprietary APIs, depending on how you build your workflow.

## Some (Not So Pretty) Pictures to Help People Visualize What It Can Do

#### Example of A Simple Assistant Workflow Using the Prompt Router

![Single Assistant Routing to Multiple LLMs](Doc_Resources/Media/Images/Wilmer-Assistant-Workflow-Example.jpg)

#### Example of How Routing Might Be Used

![Prompt Routing Example](Doc_Resources/Media/Images/Wilmer-Categorization-Workflow-Example.png)

#### Group Chat to Different LLMs

![Groupchat to Different LLMs](Doc_Resources/Media/Images/Wilmer-Groupchat-Workflow-Example.png)

#### Example of a UX Workflow Where A User Asks for a Website

![Oversimplified Example Coding Workflow](Doc_Resources/Media/Images/Wilmer-Simple-Coding-Workflow-Example.jpg)

## Key Features

* **Advanced Contextual Routing**
  The primary function of WilmerAI. It directs user requests using context-aware logic. This is handled
  by two mechanisms:
    * **Prompt Routing**: At the start of a conversation, it analyzes the user's prompt to select the most appropriate
      specialized workflow (e.g., "Coding," "Factual," "Creative").
    * **In-Workflow Routing**: During a workflow, it provides conditional "if/then" logic, allowing a process to
      dynamically choose its next step based on the output of a previous node.

  Crucially, these routing decisions can be based on the **entire conversation history**, not just the user's last
  messages, allowing for a much deeper understanding of intent.

---

* **Core: Node-Based Workflow Engine**
  The foundation that powers the routing and all other logic. WilmerAI processes requests using workflows, which are
  JSON files that define a sequence of steps (nodes). Each node performs a specific task, and its output can be passed
  as input to the next, enabling complex, chained-thought processes.

---

* **Multi-LLM & Multi-Tool Orchestration**
  Each node in a workflow can connect to a completely different LLM endpoint or execute a tool. This allows you to
  orchestrate the best model for each part of a task. For example, using a small, fast local model for summarization
  and a large cloud model for the final reasoning, all within a single workflow.

---

* **Modular & Reusable Workflows**
  You can build self-contained workflows for common tasks (like searching a database or summarizing text) and then
  execute them as a single, reusable node inside other, larger workflows. This simplifies the design of complex agents.

---

* **Stateful Conversation Memory**
  To provide the necessary context for long conversations and accurate routing, WilmerAI uses a four-part memory
  system: a chronological summary file, a continuously updated "rolling summary" of the entire chat, a searchable
  vector database (keyword search by default, with optional embedding-based semantic/hybrid search), and a
  continuously maintained state document describing the current state of the conversation.

---

* **Adaptable API Gateway**
  WilmerAI's "front door." It exposes OpenAI- and Ollama-compatible API endpoints, allowing you to connect your existing
  front-end applications and tools without modification.

---

* **Tool Calling & Structured Output**
  Full OpenAI-style tool calling passthrough, including reliable multi-round tool loops through authored-prompt
  workflows (`appendNativeToolExchange`). On backends with constrained decoding (llama.cpp, Ollama, LM Studio, vLLM,
  OpenAI), demanded tool calls (`tool_choice` forced or `required`) are grammar-enforced rather than hoped for, and
  any workflow node can pin its output to a JSON Schema (`structuredOutputFile`), turning routing decisions,
  extractions, and classifications into guaranteed-parseable JSON even on small local models. See
  `Docs/User_Documentation/Core_Features/Tool_Calling_And_Structured_Output.md`.

---

* **Flexible Backend Connectors**
  WilmerAI's "back door." It connects to various LLM backends (OpenAI, Ollama, KoboldCpp) using a simple
  configuration system of **Endpoints** (the address), **API Types** (the schema/driver), and **Presets** (the
  generation parameters).

---

- **Agentic MCP Tool Integration:** Experimental support for agentic MCP server tool
  calling, allowing the model to discover and use tools mid-workflow. Originally
  contributed by [iSevenDays](https://github.com/iSevenDays); big thank you for the
  amazing work on this feature. The transport has since been migrated to the official
  MCP SDK (MCPO remains supported as a legacy option). More info can be found in the
  [ReadMe](Public/workflow_python_scripts/_isevendays_mcp_scripts/README_MCP_TOOLS.md)

---

- **Privacy First Development:** At its core, Wilmer is continually designed with the
  principle of being completely private. Socg uses this application constantly, and doesn't
  want his information getting blasted out to the net any more than anyone else does. As such,
  every decision that is made is focused on the idea that the only incoming and outgoing calls
  from Wilmer should be things that the user expects, and actively configured themselves.

---

#### Privacy Check (2026-07-19)

For my own edification, to ensure I didn't accidentally add something that would negatively impact
Wilmer's privacy posture, I'll sometimes ask Claude Code to do an end-to-end check to look for any
outbound calls or other data leakage. It's not as good as a formal code audit, but it gives me
peace of mind. I've included the results of the check here.

I've been doing this check whenever I make a really big set of changes, just to make sure
that I didn't introduce something I didn't intend to via a library or sloppy coding.

On 2026-07-19, Claude Code (Claude Opus 4.8) was asked to search the codebase and report any outbound
network calls, telemetry, or other privacy-relevant behavior it could find. The results listed
below were generated for my own personal use and were shared for transparency; **they are not a
guarantee**.

If privacy matters to your deployment, please run your own analysis before using WilmerAI.

```text
What Was Checked
----------------
The Middleware/ and Public/ source trees, the top-level entry points (server.py, run_eventlet.py,
run_waitress.py), the Scripts/ utilities (rekey_encrypted_files.py, backfill_embeddings.py), and
all shell/batch launcher scripts (run_macos.sh, run_windows.bat, Scripts/rekey_encrypted_files.sh,
Scripts/rekey_encrypted_files.bat) were searched for outbound HTTP calls (requests.get,
requests.post, requests.Session, requests.request), raw socket usage, subprocess invocations,
dynamic imports, hardcoded external URLs, telemetry-related keywords (analytics, telemetry,
phone-home, tracking, metrics), and environment variable reads. The server entry points and
launcher scripts contained no outbound network calls; run_eventlet.py sets TCP_NODELAY on the
local listening socket but makes no external connections.

Outbound Network Calls
----------------------
The main outbound network call sites in Wilmer's own code, each targeting a destination the user
configures (this reflects the current source and is representative rather than a guaranteed
exhaustive registry; run your own analysis if it matters to you):

1. Middleware/llmapis/handlers/base/base_llm_api_handler.py and handlers/base/base_api_transport.py
   - session.post() to the user-configured LLM endpoint (self.base_url from the endpoint config);
     the streaming path posts from base_llm_api_handler.py and the non-streaming path from
     base_api_transport.py, both to the same user-configured destination

2. Middleware/workflows/tools/offline_wikipedia_api_tool.py
   - requests.get() to a user-configured host; defaults to 127.0.0.1:5728
   - Disabled unless useOfflineWikiApi is set

3. Public/workflow_python_scripts/_isevendays_mcp_scripts/mcp_service_discoverer.py
   - requests.get() to a user-configured or env-var MCPO server; defaults to localhost:8889

4. Public/workflow_python_scripts/_isevendays_mcp_scripts/mcp_tool_executor.py
   - requests.request() to the same MCPO server as above

5. Middleware/workflows/handlers/impl/web_fetch_handler.py
   - requests.request() to the URL set on a WebFetch node (user-authored); optional HTTP/SOCKS
     proxy. TLS verification is on by default.

6. Middleware/workflows/handlers/impl/curl_command_handler.py
   - spawns the system `curl` binary via subprocess.Popen (shell=False) against the URL(s) in a
     CurlCommand node's args (user-authored)

7. Middleware/workflows/tools/mcp_client_tool.py
   - connects to an MCP server defined under Public/Configs/MCPServers/ (user-configured) over
     stdio (local process), SSE, or streamable HTTP, for MCPToolCall nodes

8. Middleware/llmapis/handlers/impl/embedding_api_handler.py (via handlers/base/base_api_transport.py)
   - session.post() to the user-configured embeddings endpoint; only used when a discussion's
     memory settings configure an embeddings endpoint, or a node requests semantic or hybrid
     search against one

9. Scripts/backfill_embeddings.py
   - requests.post() only to the user-supplied --url, and only when the script is run by hand;
     never invoked by the server

No telemetry, analytics, phone-home, auto-update, or hardcoded external URLs were found. Every
outbound call Wilmer is known to make goes to a destination the user configures; there are no
connections to hosts that Wilmer picks on its own. Any optional tool or node not individually
listed above follows the same rule: it stays off unless the user enables it, and it targets only
the host the user points it at (typically defaulting to a local address). The WebFetch and
CurlCommand nodes additionally support an opt-in SSRF guard (blockPrivateAddresses / allowedHosts)
that can restrict which hosts they are allowed to reach.

Data Storage
------------
- JSON conversation/memory files: Optionally encrypted at rest using Fernet (AES-128-CBC with
  HMAC, PBKDF2 with 100k iterations) when encryptUsingApiKey is enabled.
- SQLite databases: Used for vector memory and workflow locks. These are NOT encrypted, even
  when the encryption feature is enabled.
- Log files: At DEBUG level, logs may contain full prompts and LLM responses unless
  redactLogOutput or encryptUsingApiKey is enabled in the user configuration.
- Configuration files: May contain API keys in plaintext. These files are not encrypted by Wilmer.

Third-Party Dependencies
------------------------
All runtime dependencies from requirements.txt:

  requests 2.34.2         - HTTP client for LLM API and tool calls
  urllib3 2.7.0           - Transport layer for requests
  Flask 3.1.3             - HTTP server framework
  Jinja2 3.1.6            - Template rendering for workflow prompts
  Pillow 12.3.0           - Image format detection and processing
  eventlet 0.41.1         - Async WSGI server (optional)
  waitress 3.0.2          - Production WSGI server (optional)
  cryptography 49.0.0     - Fernet encryption for stored data
  mcp 1.28.1              - Model Context Protocol client (MCPToolCall node)
  PySocks 1.7.1           - SOCKS proxy support for requests (WebFetch proxy)

No telemetry or analytics code was found in any of these packages' initialization paths as used
by Wilmer.

Dynamic Code Loading
--------------------
- PythonModule workflow nodes execute user-provided Python scripts from the configured scripts
  directory with the full privileges of the Wilmer process. These scripts are not sandboxed or
  validated by Wilmer.
- Front-end API handler discovery (Middleware/api/handlers/) uses importlib but loads only from
  that directory within the application; the backend LLM API handlers are chosen by a static
  factory rather than by scanning the filesystem.

Image URL Handling
------------------
When a conversation message contains an image referenced by HTTP URL, that URL is forwarded as-is
to the configured LLM provider. Wilmer does not fetch the image itself.

Limitations
-----------
1. This is a static source-code search performed by an AI (Claude Opus 4.8), not a formal third-party
   security audit.
2. Third-party library source code was not checked at the bytecode level. The results confirm only
   that Wilmer's own code does not appear to initiate unexpected connections.
3. PythonModule scripts are user-provided and can execute arbitrary code. Their behavior is outside
   the scope of this check.
4. Runtime network monitoring (e.g., packet capture) was not performed.
5. SQLite databases used for vector memory are not encrypted, even when encryption is otherwise
   enabled.
6. Log files may contain full conversation content unless redaction is explicitly enabled.
```

> While I do not have the tools to make a 100% guarantee claim there is not a third party
> library doing something I'm not expecting, I wanted to make a point
> that this is something that is important to me. I highly recommend, if you have
> any concerns, that you run your own analysis of the codebase and app. Please open an issue
> if you ever find anything that I've missed.

## User Documentation

User Documentation can be found by going to [/Docs/User_Documentation/](Docs/User_Documentation/README.md)

## Developer Documentation

Helpful developer docs can be found in [/Docs/Developer_Docs/](Docs/Developer_Docs/README.md)

## Quick-ish Setup

WilmerAI requires Python 3.11.9 or newer (3.10.14+, 3.12.4+, or any 3.13+ also work). The
3.11.9 floor is deliberate: it is the first 3.11 release with the CVE-2024-4032 fix that
corrects `ipaddress`'s classification of several non-public address ranges, which the
optional SSRF address guard (`blockPrivateAddresses` / `allowedHosts`) relies on.

### Guides

#### WilmerAI

Hop into the [User Documents Setup Starting Guide](Docs/User_Documentation/Setup/_Getting-Start_Wilmer-Api.md) to get
step by step rundown of how to quickly set up the API.

#### Wilmer with Open WebUI

[You can click here to find a written guide for setting up Wilmer with Open WebUI](Docs/User_Documentation/Setup/Open-WebUI.md)

#### Wilmer With SillyTavern

[You can click here to find a written guide for setting up Wilmer with SillyTavern](Docs/User_Documentation/Setup/SillyTavern.md).


---

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

- Claude API (Anthropic Messages API)
- OpenAI Compatible v1/completions
- OpenAI Compatible chat/completions
- Ollama Compatible api/generate
- Ollama Compatible api/chat
- KoboldCpp Compatible api/v1/generate (*non-streaming generate*)
- KoboldCpp Compatible /api/extra/generate/stream (*streaming generate*)

Wilmer supports both streaming and non-streaming connections, and has been tested using both Sillytavern
and Open WebUI.

## Maintainer's Note:

> This project is being supported in my free time on my personal hardware. I do not have the ability to contribute to
> this during standard business hours on
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

---

## Contact

For feedback, requests, or just to say hi, you can reach me at:

WilmerAI.Project@gmail.com

---

## Third Party Libraries

WilmerAI imports several libraries within its requirements.txt, and imports the libraries via import statements; it does
not extend or modify the source of those libraries.

The libraries are:

* Flask : https://github.com/pallets/flask/
* requests: https://github.com/psf/requests/
* urllib3: https://github.com/urllib3/urllib3/
* jinja2: https://github.com/pallets/jinja
* pillow: https://github.com/python-pillow/Pillow
* eventlet: https://github.com/eventlet/eventlet
* waitress: https://github.com/Pylons/waitress
* cryptography: https://github.com/pyca/cryptography
* mcp: https://github.com/modelcontextprotocol/python-sdk
* PySocks: https://github.com/Anorov/PySocks

Further information on their licensing can be found within the README of the ThirdParty-Licenses folder, as well as the
full text of each license and their NOTICE files, if applicable, with relevant last updated dates for each.

## Wilmer License and Copyright

    WilmerAI
    Copyright (C) 2024-2026 Christopher Smith

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
