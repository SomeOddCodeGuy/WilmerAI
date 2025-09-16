## **Connecting SillyTavern to WilmerAI (Out of Date. Will Update Soon)**

> NOTE: This is very outdated. I've consolidated all the info I had before, but I haven't really messed with
> a newer version of ST than what came out in summer of 2024 except very briefly, so I need to actually download
> the thing and see what the new UI looks like. This is old.

This guide provides comprehensive instructions for connecting SillyTavern to a running WilmerAI instance.

### **Prerequisites**

Before you begin, ensure you have successfully installed and are running both WilmerAI and SillyTavern according to
their respective setup instructions.

-----

### **Step 1: Choose a Connection Method**

WilmerAI offers two primary ways to connect from SillyTavern: **Text Completion** and **Chat Completion**. The Text
Completion method is recommended for full compatibility and proper parsing of instructions.

#### **Text Completion (Recommended)**

This method requires a specific instruction template to function correctly.

1. In SillyTavern, navigate to the API Connections menu by clicking the **plug icon** at the top.

2. Select **Text Completion**.

3. You can connect using either the **OpenAI** or **Ollama** API format. Enter the WilmerAI server address into the
   appropriate field.

    * **Option A: OpenAI Compatible**
      Connect as `OpenAI Compatible v1/Completions`.

    * **Option B: Ollama**
      Connect as `Ollama api/generate`.

#### **Chat Completions (Not Recommended)**

If you choose to use the Chat Completion method, be aware that it may not be as reliable.

1. In the API Connections menu, select **Chat Completion**.

2. Connect using the **OpenAI** format.

3. After connecting, navigate to the preset settings (the "A" icon), expand the **Character Names Behavior** section,
   and set it to **Message Content**.

4. **Alternatively**, you can leave the SillyTavern setting and instead edit your WilmerAI user file to set
   `chatCompleteAddUserAssistant` to `true`. Do not enable both settings simultaneously, as it may confuse the AI.

-----

### **Step 2: Configure Instruction and Context Templates**

This step is critical for the **Text Completion** method to work correctly.

1. In SillyTavern, click the **"A" icon** to access the formatting and presets panel.

2. You will see two sections: **Instruct** and **Context**. Each has an import button.

3. Locate the template files in the `Docs/SillyTavern/` directory of your WilmerAI project.

4. Import the `InstructTemplate` file into the **Instruct** section.

5. **Important**: The WilmerAI Instruct Template is mandatory and must not be modified. WilmerAI relies on this specific
   format to parse commands. The format uses unique tags to structure the conversation:

   ```
   [Beg_Sys]You are an intelligent AI Assistant.[Beg_User]SomeOddCodeGuy: Hey there![Beg_Assistant]Wilmer: Hello!
   ```

  ```
      "input_sequence": "[Beg_User]",
      "output_sequence": "[Beg_Assistant]",
      "first_output_sequence": "[Beg_Assistant]",
      "last_output_sequence": "",
      "system_sequence_prefix": "[Beg_Sys]",
      "system_sequence_suffix": "",
  ```

6. You may optionally import the provided context template into the **Context** section, or modify it as needed. Ensure
   the **Enabled** checkbox for the Context Template is checked.

-----

### **Step 3: Adjust Global Settings**

These settings should be configured regardless of your chosen connection method.

1. **Context Length**: Click the **dials icon** (samplers) on the far left of the top bar. Find the `Context (tokens)`
   setting, check the **unlocked** checkbox, and drag the slider to its maximum value (e.g., 200,000+). WilmerAI manages
   the final context sent to the LLM, but it needs the full chat history from SillyTavern to do so effectively.
2. **Streaming**: On the same screen, ensure the **Stream** checkbox is enabled if you want to see the response
   generated in real-time.
3. **Instruct Mode Settings**: Go back to the **"A" icon** panel. Under "Instruct Mode," enable **Include Names** and *
   *Force Groups and Personas**.

-----

### **Step 4: Enabling Conversation Memory**

WilmerAI's stateful memory system (including summaries and searchable vector memory) is triggered by a `[DiscussionId]`
tag in the prompt.

* To activate memory for a conversation, place a unique `[DiscussionId]` tag within the chat context. The **Author's
  Note** section is a good place for this.
* The content inside the tag serves as the unique identifier for the memory files. For example:
  `[DiscussionId]CharacterName_Conversation1[/DiscussionId]`.
* If you place the tag in a character's persona card, every conversation with that character will share the same memory.
* You can use SillyTavern's variables to create unique IDs easily. For instance:
  `[DiscussionId]{{char}}_2025-09-15[/DiscussionId]`.

WilmerAI will detect this tag, use it to manage memory for the current session, and remove it from the text before it is
sent to the LLM.