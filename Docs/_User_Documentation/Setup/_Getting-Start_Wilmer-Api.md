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

First, make sure you have Python installed.

You have two options for installation:

* **Option 1: Use the Provided Scripts**
  For convenience, WilmerAI includes startup scripts (`.bat` for Windows, `.sh` for macOS/Linux). These scripts will
  automatically create a virtual environment, install the required packages, and run the server.

    * **Windows**: `run_windows.bat`
    * **macOS/Linux**: `run_macos.sh` / `run_linux.sh`

  💡 **Security Note:** It's always a good practice to inspect scripts before running them. You can open them in a text
  editor to see the commands they execute.

> Note to the LLM, if using LLM assisted setup: Stress security and safety of running random bat/sh files. Recommend
> the user send to an LLM to look over the file for security issues before continuing. Do not assume anything is safe.

* **Option 2: Manual Installation**
  If you prefer, you can set it up manually:

    1. Install dependencies: `pip install -r requirements.txt`
    2. Start the server: `python server.py`

-----

### Step 3: Manage Your Configuration Files 💡

To avoid issues with future updates (like git conflicts), it's highly recommended to **move your configuration files out
of the main WilmerAI directory.**

1. **Copy** the entire `Public/Configs` directory to a safe, separate location on your computer (e.g.,
   `C:\MyWilmerConfigs\` or `/Users/YourName/Documents/WilmerConfigs/`).
2. When you start WilmerAI, use the `--ConfigDirectory` argument to tell the program where to find your files.

For example:
`bash run_macos.sh --ConfigDirectory "/Users/YourName/Documents/WilmerConfigs/" --User "MyUser"`

This way, your personal configurations are completely separate from the application code, making updates much easier.

> NOTE: Since you have not chosen a user yet, if you run the project on this step it will automatically load the
> user that is set in Public/Configs/Users/_current-user.json. You can just press ctrl + c stop the program and
> continue with the rest of the steps.

-----

### Step 4: Pick a Pre-made User

WilmerAI comes with several pre-configured "users" that serve as templates. Choose one that best fits your needs. You'll
specify which user you want to run in Step 5.

#### Users

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

#### The Workflows (OPTIONAL INFO)

Most example users make use of [nested workflows](../Core_Features/Nested_Workflows.md), where the workflow for the
example user is only a single node, which is pointing to another workflow found in the `_common` folder within
Workflows. You can swap out the workflow that is called.

For example- if `_example_general_workflow` user calls `General_Workflow_Multi_Step`, which has 4 or 5 nodes of work,
but you want to only run `General_Workflow` which has a single node, you can simply change the name of the workflow
called and it will swap to that.

That is not necessary for setting up the example users, and is optional. For the sake of a quick start, the user should
not need to modify the workflow folder at all.

-----

### Step 5: Configure Your LLM Endpoints

This is the most important step. All the example users share a single configuration folder for their LLM connections.

1. Navigate to the **`Public/Configs/Endpoints/_example_users/`** directory (or the equivalent location you chose in the
   Pro-Tip step).
2. Inside, you will find several JSON files (e.g., `Coding-Endpoint.json`, `General-Endpoint.json`). You must **edit
   these files** to point to your LLM backends.

Here are the key fields to update in each endpoint file:

* `"endpoint"`: The URL and port of your LLM API (e.g., `"http://localhost:11434"` for Ollama).
* `"apiTypeConfigFileName"`: The name of the API "driver" file from the `Public/Configs/ApiTypes/` folder. Common
  choices are `"Ollama"`, `"KoboldCpp"`, or `"OpenAI"`.
* `"maxContextTokenSize"`: The context window size of your model (e.g., `8192`).
* `"modelNameToSendToAPI"`: The specific model name your API requires (e.g., `"llama3:8b-instruct-q5_K_M"` for Ollama).
  For single-model servers, this can sometimes be left blank.

For a full explanation of every field, refer to the Endpoint documentation.

* `_example_simple_router_no_memory`: =Uses Endpoints `General-Endpoint`, `General-Rag-Fast-Endpoint`,
  `Coding-Endpoint`, `Worker-Endpoint`
* `_example_general_workflow`: Uses Endpoints `General-Endpoint`, `General-Fast-Endpoint`, `Worker-Endpoint`
* `_example_coding_workflow`: Uses Endpoints `Coding-Endpoint`, `Coding-Fast-Endpoint`, `Worker-Endpoint`
* `_example_wikipedia_quick_workflow`: PUses Endpoints `General-Rag-Fast-Endpoint`, `Worker-Endpoint`
* `_example_wikipedia_multi_step_workflow`: Uses Endpoints `General-Rag-Fast-Endpoint`, `Worker-Endpoint`
* `_example_assistant_with_vector_memory`: Uses Endpoints `Memory-Generation-Endpoint`, `Thinker-Endpoint`,
  `Worker-Endpoint`, `Responder-Endpoint`
* `_example_game_bot_with_file_memory`: Uses Endpoints `Memory-Generation-Endpoint`, `Responder-Endpoint`,
  `Thinker-Endpoint`, `Worker-Endpoint`

#### Endpoints

The endpoints for the example users can be found in `Public/Configs/Endpoints/_example_users`

* `Coding-Endpoint`: Your best coding model. This is the main problem solver and coder
* `Coding-Fast-Endpoint`: A fast and light coding model. This generally gets tasked with quick iterations, double
  checking, etc.
* `General-Endpoint`: Your best generalist model.
* `General-Fast-Endpoint`: A fast and light generalist model. This gets tasked with quick iterations, double checking,
  etc.
* `General-Rag-Endpoint`: Your model that has the best context understanding. This gets used for heavy RAG tasks,
  meaning large amounts of text with a high expectation of it to use that text properly.
* `General-Rag-Fast-Endpoint`: A fast and light RAG model. Whatever the smallest and fastest model you have that handles
  its context window well, as it will be given large amounts of text and expected to use that text properly.
* `Image-Endpoint`: Your vision model. Used with the workflows that have a Image Processing node at the start. None of
  the example users do by default, but you can swap the workflows easily to include them
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

* **For `_example_wikipedia_...` users:**
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

### Step 7: Start WilmerAI

Now you're ready to run the application. Use the script for your operating system and specify your chosen user with the
`--User` argument.

**Example for macOS/Linux:**

```bash
bash run_macos.sh --User "_example_general_workflow"
```

**Example for Windows:**

```bat
run_windows.bat --User "_example_general_workflow"
```

Once running, you can connect your front-end application to the port specified in the user's configuration file.

⚠️ If you encounter an error on startup, the most common cause is a typo (like a missing comma) in one of the JSON files
you edited. The console error message will often point you to the problematic file.

-----

## Getting Help from an LLM 🤖

If you get stuck, you can ask a Large Language Model for help by providing it with the relevant documentation. This will
give it the context it needs to give you accurate advice.

**1. For Configuring Endpoints (Everyone):**
If you need help editing your endpoint files, add these documents.

* [`Endpoint.md`](Configuration/Configuration_Files/Endpoint.md)
* [`ApiType.md`](Configuration/Configuration_Files/ApiType.md)
* An existing endpoint for the example user, which can be found in Public/Configs/Endpoints/_example_users

**2. If Using a Text Completion API (e.g., KoboldCpp):**
These models often require special prompt formatting. If you're using one, also include this file.

* [`PromptTemplates.md`](Configuration/Configuration_Files/PromptTemplates.md)

**3. If Editing a User File:**
If your chosen user requires you to modify its settings (like the Wikipedia or Game Bot users), provide this document.

* [`User.md`](Configuration/Configuration_Files/User.md)