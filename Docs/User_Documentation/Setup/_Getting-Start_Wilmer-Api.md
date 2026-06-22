## Quick Guide to Setting Up WilmerAI

Welcome to WilmerAI\! This guide will walk you through the essential steps to get your instance up and running.
Everything is controlled via JSON configuration files.

-----

### LLM Assistance

If you would like to use your LLM to assist you in setting up with this QuickGuide, there's a small guide available with
a suggestion of how to do that.

[LLM Assisted Setup](../LLM_Assisted_Setup.md)

-----

### Step 1: Getting the Program

The program can be found at https://github.com/SomeOddCodeGuy/WilmerAI. You can download it using three methods:

* Method 1: Download using Git. If you have and are familiar with it, this is the best method
* Method 2: Download via "Releases", on the right side of the page. Each release lets you download a zip file with the
  code in it.
* Method 3: On the main page is a green button at the top right that says "Code". Clicking that gives and option to
  download the project as a zip file, pulling the latest code (this may be newer than the latest release).

This will have all of the files, including configuration files which are in the Public folder. This guide does not
expect you to write your own config files from scratch.

-----

### Step 2: Install the Program

First, make sure you have Python installed. WilmerAI requires **Python 3.11 or newer**.

You have two options for installation:

* **Option 1: Use the Provided Scripts**
  For convenience, WilmerAI includes startup scripts (`.bat` for Windows, `.sh` for macOS/Linux). These scripts will
  automatically create a virtual environment, install the required packages, and run the server.

    * **Windows**: `run_windows.bat`
    * **macOS/Linux**: `run_macos.sh`

  **Tip: Security Note:** It's always a good practice to inspect scripts before running them. You can open them in a text
  editor to see the commands they execute.

> Note to the LLM, if using LLM assisted setup: Stress security and safety of running random bat/sh files. Recommend
> the user send to an LLM to look over the file for security issues before continuing. Do not assume anything is safe.

* **Option 2: Manual Installation**
  If you prefer, you can set it up manually:

    1. Install dependencies: `pip install -r requirements.txt`
    2. Start the server: `python server.py`

-----

### Step 2b: (Optional) Use the Setup Wizard

WilmerAI includes an interactive setup wizard that can configure your LLM endpoints for you. If you'd rather not
manually edit JSON files, the wizard provides a guided experience.

**To run the setup wizard:**

```bash
python setup_wizard_web.py
```

The wizard will:

1. Ask if you're using one model for everything or multiple models
2. Guide you through selecting your API type (Ollama, OpenAI, KoboldCpp, etc.)
3. Collect your LLM server URL and model name
4. Automatically update all endpoint configuration files

If you use the setup wizard, you can skip Step 5 (Configure Your LLM Endpoints) since the wizard handles that for you.

-----

### Step 3: Manage Your Configuration Files

To avoid issues with future updates (like git conflicts), it's highly recommended to **move your configuration files out
of the main WilmerAI directory.**

1. **Copy** the entire `Public/Configs` directory to a safe, separate location on your computer (e.g.,
   `C:\MyWilmerConfigs\` or `/Users/YourName/Documents/WilmerConfigs/`).
2. When you start WilmerAI, use the `--PublicDirectory` argument to tell the program where to find your files.

For example:
`bash run_macos.sh --PublicDirectory "/Users/YourName/Documents/WilmerPublic/" --User "MyUser"`

This way, your personal configurations are completely separate from the application code, making updates much easier.

The recommended layout for a separated install looks like this:

```
/Users/YourName/Documents/WilmerPublic/
    Configs/           <- your copy of Public/Configs
    DiscussionIds/     <- created on first use
    SqlLiteDBs/        <- created on first use
    logs/              <- created on first use when file logging is on
```

When `--PublicDirectory` is set, all runtime data that WilmerAI creates during execution lands in sibling subfolders
under that directory by default, so a shared install never leaks per-user data back into the application folder.
Critically, runtime data lives *alongside* `Configs/`, never inside it:

| Data | Default location when `--PublicDirectory` is set |
|---|---|
| Configs | `{PublicDirectory}/Configs/` (override with `--ConfigDirectory` for backwards compat) |
| Log files | `{PublicDirectory}/logs/` (override with `--LoggingDirectory`) |
| Workflow lock SQLite DBs | `{PublicDirectory}/SqlLiteDBs/` (override with `--UserLevelSqlLiteDirectory` or the `sqlLiteDirectory` user config setting) |
| Per-discussion files (memories, summaries, vector DBs) | `{PublicDirectory}/DiscussionIds/` (override with `--DiscussionDirectory` or the `discussionDirectory` user config setting) |

When **no** flag is set, every default above resolves to a subfolder under `{install_dir}/Public/` — where
`{install_dir}` is the directory containing `server.py`. The defaults are pinned to the install location (derived from
the Python source files), so they never depend on the current working directory. If you run WilmerAI from an unusual
cwd (e.g. as a systemd service, or by launching the script from your home directory), logs and runtime data still
land inside the install tree rather than quietly appearing in `~/logs/` or `/logs/`.

`--ConfigDirectory` is still supported for backwards compatibility and continues to point specifically at a
`Public/Configs/` folder, but it no longer governs where runtime data lands. If you want the consolidated shared-install
behavior, prefer `--PublicDirectory`.

If data already exists at pre-refactor locations (e.g. `Public/DiscussionIds/` or a lock database in the project root),
WilmerAI keeps reading and writing to that existing location -- no automatic migration is performed. Move the files
manually if you want them under the new location.

> NOTE: Since you have not chosen a user yet, if you run the project on this step it will automatically load the
> user that is set in Public/Configs/Users/_current-user.json. You can just press ctrl + c stop the program and
> continue with the rest of the steps.

-----

### Step 4: Pick a Pre-made User

WilmerAI comes with several pre-configured "users" that serve as templates. Choose one that best fits your needs. You'll
specify which user you want to run in Step 5.

#### Users

* **`_simple_router_no_memory`**: A simple user that uses prompt routing to send each request to a category-specific
  workflow. It ships with two categories, `WIKI` and `GENERAL`. Best used with direct and productive front ends like
  Open WebUI. The `WIKI` route requires the Offline Wikipedia API.


* **`chat-ui`** (and three variants): The out-of-the-box default user (`_current-user.json` points to it). Rather than
  tying one user to one workflow, `chat-ui` is built around the **shared workflows** system: it points at the `_shared`
  workflow folder, which contains several ready-to-use workflows (`general`, `fast`, `general-reasoning`,
  `fast-reasoning`, and `task`). Front ends like Open WebUI query the `/v1/models` endpoint and let you pick any of
  them from the model dropdown, so one user replaces the handful of single-purpose users you would otherwise need. See
  "Shared Workflows" below for more details.

  There are four flavors that differ only in which shared workflow folder they load:

    * **`chat-ui`** (`_shared`): the standard workflows. Images are passed directly on the workflow nodes, so a vision
      model can consume them as needed.
    * **`chat-ui-cot`** (`_shared_manual_cot`): the same workflows, but the reasoning roles enforce a **manual
      chain-of-thought** step. Use this for models whose native reasoning is broken or absent, where you want the
      workflow to drive the reasoning instead.
    * **`chat-ui-discussionid`** (`_shared_discussionid`): expects a `discussionId` on the request. Image handling
      differs here: a dedicated vision node describes the image in fine detail, and Wilmer stores that description and
      re-injects it at the correct position in the conversation for as long as that turn stays inside the model's
      context window. This lets non-vision models "see" an earlier image and avoids re-encoding it every turn.
    * **`chat-ui-cot-discussionid`** (`_shared_manual_cot_discussionid`): combines the manual chain-of-thought and the
      discussionId vision behavior.


* **`_wikipedia_quick_workflow`**: A single-pass wikipedia search against the Offline Wikipedia API.
  Requires the Offline Wikipedia API


* **`_wikipedia_multi_step_workflow`**: A wikipedia search against the Offline Wikipedia API, but
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

#### The Workflows (OPTIONAL INFO)

The `chat-ui` users make use of [nested workflows](../Core_Features/Nested_Workflows.md): each shared workflow under
`_shared` is a single node that points to a reusable workflow in the `_common` folder within Workflows. For example,
`_shared/general/_DefaultWorkflow.json` is one `CustomWorkflow` node that calls `General` from `_common`. You can swap
out the workflow that is called.

For example, you could change that node's `workflowName` from `General` to `Task` (or any other entry in `_common`) by
editing the `_DefaultWorkflow.json` for that shared workflow. Common workflows in `_common` include:

* `General` - General conversation
* `General_CoT` - General conversation with an enforced manual chain-of-thought step
* `General_With_Vision_DiscussionId` - General conversation that uses a discussionId vision node to describe and persist images
* `Task` - Task-oriented workflow
* `Direct_Model` - Sends the conversation straight to a single model with no extra steps

That is not necessary for setting up the example users, and is optional. For the sake of a quick start, the user should
not need to modify the workflow folder at all.

-----

### Step 5: Configure Your LLM Endpoints

This is the most important step. Each example user points at its own endpoint collection under
`Public/Configs/Endpoints/`, selected by the user's `endpointConfigsSubDirectory` setting. The four `chat-ui` users use
the `_shared*` collections; the other users have their own.

> **Tip:** If you prefer a guided experience, run `python setup_wizard_web.py` instead of manually editing these files.
> The setup wizard will configure all your endpoints interactively.

1. Navigate to the endpoint collection for the user you picked, e.g. **`Public/Configs/Endpoints/_shared/`** for the
   `chat-ui` user (or the equivalent location you chose in the Pro-Tip step). The collection name matches the user's
   `endpointConfigsSubDirectory` setting.
2. Inside, you will find several JSON files (e.g., `General-Endpoint.json`, `Worker-Endpoint.json`). You must **edit
   these files** to point to your LLM backends.

Here are the key fields to update in each endpoint file:

* `"endpoint"`: The URL and port of your LLM API (e.g., `"http://localhost:11434"` for Ollama).
* `"apiTypeConfigFileName"`: The name of the API "driver" file from the `Public/Configs/ApiTypes/` folder. Common
  choices are `"Ollama"`, `"KoboldCpp"`, or `"OpenAI"`.
* `"maxContextTokenSize"`: The context window size of your model (e.g., `8192`).
* `"modelNameToSendToAPI"`: The specific model name your API requires (e.g., `"llama3:8b-instruct-q5_K_M"` for Ollama).
  For single-model servers, this can sometimes be left blank.

For a full explanation of every field, refer to the Endpoint documentation.

* `chat-ui` / `chat-ui-discussionid`: Collection `_shared` (or `_shared_discussionid`). Endpoints `General-Endpoint`,
  `General-Reasoning-Endpoint`, `Fast-Endpoint`, `Fast-Reasoning-Endpoint`, `Worker-Endpoint` (the `_discussionid`
  collection also includes `Vision-Endpoint`).
* `chat-ui-cot` / `chat-ui-cot-discussionid`: Collection `_shared_manual_cot` (or `_shared_manual_cot_discussionid`).
  Endpoints `General-Endpoint`, `Fast-Endpoint`, `Worker-Endpoint` (the `_discussionid` collection also includes
  `Vision-Endpoint`). The manual chain-of-thought workflows drive the reasoning themselves, so these collections do not
  ship the `*-Reasoning-Endpoint` models.
* `_simple_router_no_memory`: Collection `_simple_router_no_memory`. Endpoints `General-Endpoint`,
  `General-Reasoning-Endpoint`, `Rag-Fast-Endpoint`, `Fast-Endpoint`, `Fast-Reasoning-Endpoint`,
  `Worker-Endpoint`
* `_wikipedia_quick_workflow` and `_wikipedia_multi_step_workflow`: Collection `_example_wikipedia`. Endpoints
  `Rag-Fast-Endpoint`, `Vision-Endpoint`
* `_example_assistant_with_vector_memory` and `_example_game_bot_with_file_memory`: Collection `_example_users`.
  Endpoints `Memory-Generation-Endpoint`, `Thinker-Endpoint`, `Responder-Endpoint`, `Worker-Endpoint`, `Vision-Endpoint`

#### Endpoints

The endpoint roles used across the collections are described below. Not every collection contains every role; each user
only ships the endpoints its workflows actually reference.

* `General-Endpoint`: Your best generalist model.
* `General-Reasoning-Endpoint`: A generalist model used where the workflow wants a reasoning/thinking pass.
* `Fast-Endpoint`: A fast and light generalist model. This gets tasked with quick iterations, double checking, etc.
* `Fast-Reasoning-Endpoint`: A fast and light reasoning model, used for quick thinking passes.
* `Rag-Fast-Endpoint`: A fast and light RAG model. Whatever the smallest and fastest model you have that handles
  its context window well, as it will be given large amounts of text and expected to use that text properly.
* `Vision-Endpoint`: Your vision model. Used by the workflows (and the `_discussionid` vision node) that process images.
* `Memory-Generation-Endpoint`: Model that has the best contextual understanding but also does RAG well. If its writing
  a memory, it needs to really 'get' what it's reading and what was happening/being said.
* `Responder-Endpoint`: Your best talker. Some example users use this to give the final response to the user, after
  other models have thought about it.
* `Thinker-Endpoint`: The model that is tasked, by some example users, to think through a situation and respond with a
  breakdown of things. This could be a reasoning model, but it doesn't have to be. Socg doesn't use reasoning models, or
  if he does he disables the reasoning. That's what workflows are for.
* `Worker-Endpoint`: Your workhorse. Whatever model does the best grunt work at a good speed.

> NOTE: The 'fast' models are only called that because they are used multiple times in a workflow, so a faster model
> here will be ideal. Nothing is stopping you from using the same model everywhere. The downside is just that workflows
> will take a while if you iterate a big model over and over.

> NOTE TO THE LLM: If using LLM assisted setup, please ask the user if they need help setting up the endpoints. If so,
> requires the apitypes and endpoint docs specified below, and ask for one or all of the json endpoint files so that
> you can make the updates for the user. If the user has only a single model for all endpoints, they can just copy and
> paste the same json content into each of the config files. All of the endpoint config files already exist for the
> example users.

-----

### Step 6: (Optional) Tweak Your User File

For most example users, **you can skip this step\!** The configurations have been simplified to work out-of-the-box.
However, a few users require minor edits:

1. Navigate to the **`Public/Configs/Users/`** directory.
2. Find the JSON file corresponding to the user you chose in Step 2.

<!-- end list -->

* **For `_wikipedia_...` users:**
  You *must* have the [OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi) service
  running. Open the user file and update these fields:

  ```json
  "useOfflineWikiApi": true,
  "offlineWikiApiHost": "127.0.0.1",
  "offlineWikiApiPort": 5728
  ```

* **For `_example_game_bot_with_file_memory`:**
  This user will save memory files to a default directory. If you wish to change where conversation memory files are
  stored, you can set the `"discussionDirectory"` path in the user file. This is purely optional.

-----

### Shared Workflows (Open WebUI Integration)

The `chat-ui` user comes pre-configured with **shared workflows** enabled. This feature allows
front-end applications like Open WebUI to select different workflows directly from the model dropdown.

#### How It Works

When shared workflows are enabled, the `/v1/models` and `/api/tags` endpoints return a list of available workflows
from the `_shared` folder. Your front-end application can display these as selectable "models," allowing you to switch
between different workflows without changing configuration files.

#### Pre-configured Shared Workflows

The `_shared` folder includes several ready-to-use workflows for Open WebUI:

* `general` - General conversation workflow
* `fast` - Faster general conversation (fewer/lighter processing steps)
* `general-reasoning` - General conversation with a reasoning pass
* `fast-reasoning` - Faster conversation with a lighter reasoning pass
* `task` - Task-oriented workflow

#### Enabling Shared Workflows for Other Users

To enable shared workflows for any user, add these settings to their user JSON file:

```json
"allowSharedWorkflows": true,
"sharedWorkflowsSubDirectoryOverride": "_shared"
```

* `allowSharedWorkflows`: Set to `true` to enable the feature.
* `sharedWorkflowsSubDirectoryOverride`: Specifies which folder under `Workflows/` to load shared workflows from.
  The default `_shared` folder contains workflows designed for Open WebUI.

#### Using Shared Workflows

1. Connect your front-end (e.g., Open WebUI) to WilmerAI
2. Query the models list (your front-end does this automatically)
3. Select a workflow from the model dropdown (e.g., `chat-ui:general`)
4. Your requests will now use the selected workflow

-----

### Step 7: Start WilmerAI

Now you're ready to run the application. Use the script for your operating system and specify your chosen user with the
`--User` argument.

**Example for macOS/Linux:**

```bash
bash run_macos.sh --User "chat-ui"
```

**Example for Windows:**

```bat
run_windows.bat --User "chat-ui"
```

By default, WilmerAI only listens on `127.0.0.1` (localhost). If you need to connect from another machine on the
network, add `--listen`:

```bash
bash run_macos.sh --User "chat-ui" --listen
```

> **UPDATE:** WilmerAI previously defaulted to listening on `0.0.0.0` (all network interfaces). It now defaults
> to `127.0.0.1` (localhost only). If your front-end runs on a different machine and you were relying on the old
> behavior, add `--listen` to your launch command.

Once running, you can connect your front-end application to the port specified in the user's configuration file.

**Important:** If you encounter an error on startup, the most common cause is a typo (like a missing comma) in one of the JSON files
you edited. The console error message will often point you to the problematic file.

#### Optional: Multi-User Mode

If multiple users share the same LLM hardware, you can serve them from a single Wilmer instance instead of running
separate instances. Specify `--User` multiple times:

```bash
bash run_macos.sh --User "user-one" --User "user-two" --User "user-three"
```

```bat
run_windows.bat --User "user-one" --User "user-two" --User "user-three"
```

Each user must have a configuration file in `Public/Configs/Users/`. Front-ends select a user by setting the model
field (e.g., `"model": "user-two"` or `"model": "user-two:coding"`). The `/v1/models` and `/api/tags` endpoints
list models from all configured users.

In multi-user mode, the per-user `port` config setting is ignored. Use the `--port` flag to specify the listening
port. If omitted, it defaults to `5050`:

```bash
bash run_macos.sh --User "user-one" --User "user-two" --port 5555
```

The concurrency gate applies to all users' requests together, serializing access to shared hardware.

#### Optional: Concurrency Limiting

By default, WilmerAI serializes requests (`--concurrency 1`), processing one at a time. If your backend can handle
parallel requests and you want to allow them, set `--concurrency 0`:

```bash
bash run_macos.sh --User "chat-ui" --concurrency 0
```

```bat
run_windows.bat --User "chat-ui" --concurrency 0
```

For full details on concurrency limiting, see [Concurrency Limiting](../Core_Features/Concurrency_Limiting.md).

-----

## Getting Help from an LLM

If you get stuck, you can ask a Large Language Model for help by providing it with the relevant documentation. This will
give it the context it needs to give you accurate advice.

**1. For Configuring Endpoints (Everyone):**
If you need help editing your endpoint files, add these documents.

* [`Endpoint.md`](Configuration_Files/Endpoint.md)
* [`ApiType.md`](Configuration_Files/ApiType.md)
* An existing endpoint for the user you picked, found in the endpoint collection under `Public/Configs/Endpoints/`
  that matches the user's `endpointConfigsSubDirectory` (e.g. `_shared` for the `chat-ui` user)

**2. If Using a Text Completion API (e.g., KoboldCpp):**
These models often require special prompt formatting. If you're using one, also include this file.

* [`PromptTemplates.md`](Configuration_Files/PromptTemplates.md)

**3. If Editing a User File:**
If your chosen user requires you to modify its settings (like the Wikipedia or Game Bot users), provide this document.

* [`User.md`](Configuration_Files/User.md)