## **The Default Example Endpoints and Presets**

WilmerAI ships with several example users, and those come with pre-defined endpoints and presets that are meant to be
updated with connection info from the user, so that they can be used in workflows.

While it is impossible to know what endpoints a user has available without them detailing it, it is a safe bet when
writing any workflow that the user will likely have endpoints matching these names. It is on the user to express
otherwise.

Endpoints live in `Public/Configs/Endpoints/<collection>/` and presets live in
`Public/Configs/Presets/<ApiPresetType>/<collection>/` (one preset folder per backend type). **Every preset is named to
match the endpoint it pairs with:** `General-Endpoint` -> `General-Preset`, `Worker-Endpoint` -> `Worker-Preset`,
`Vision-Endpoint` -> `Vision-Preset`, and so on. If a node uses an endpoint named `X-Endpoint`, expect a preset named
`X-Preset` in the active preset collection.

-----

### The Shared Collections

Most example users draw from one of four interchangeable "shared" collections. All four expose the same role names, so a
workflow written against one runs against any of them; the only differences are how reasoning is produced and whether
images are handled.

| Collection          | Folder                            | Reasoning                                          | Images                              |
|---------------------|-----------------------------------|----------------------------------------------------|-------------------------------------|
| Base                | `_shared`                         | Native (the reasoning roles think for themselves)  | No                                  |
| Manual CoT          | `_shared_manual_cot`              | Enforced by the workflow; model thinking disabled  | No                                  |
| Base + Vision       | `_shared_discussionid`            | Native                                             | Yes, via a discussion-id vision node |
| Manual CoT + Vision | `_shared_manual_cot_discussionid` | Enforced by the workflow; model thinking disabled  | Yes, via a discussion-id vision node |

#### Roles

* `General-Endpoint` / `General-Preset`: Your best generalist model. Non-reasoning; thinking disabled.
* `General-Reasoning-Endpoint` / `General-Reasoning-Preset`: Your best generalist reasoning model. Thinking enabled.
  Present only in the non-CoT collections (`_shared`, `_shared_discussionid`).
* `Fast-Endpoint` / `Fast-Preset`: A small, fast generalist. Non-reasoning; thinking disabled.
* `Fast-Reasoning-Endpoint` / `Fast-Reasoning-Preset`: A small, fast reasoning model. Thinking enabled. Present only in
  the non-CoT collections.
* `Worker-Endpoint` / `Worker-Preset`: The workhorse for grunt-work task nodes. Thinking disabled.
* `Vision-Endpoint` / `Vision-Preset`: The vision model. Present only in the `*_discussionid` collections. The vision
  node writes its description of an image to the discussion's files, so the image is not reprocessed on later turns.

#### Native reasoning vs. manual chain-of-thought

The reasoning roles (`*-Reasoning`) exist only in the base and vision collections, where a reasoning-capable model is
trusted to think on its own (thinking enabled).

The `*_cot` collections drop those reasoning roles. In them, a request that would have gone to a reasoning model is
instead routed through a manual chain-of-thought workflow whose **thinker and responder both run on the plain,
non-reasoning `Fast` or `General` model with thinking disabled**. This is the option for models that lack reasoning, or
whose native reasoning is unreliable: the workflow supplies the reasoning step explicitly rather than relying on the
model.

Whether "thinking disabled" can be enforced from the preset depends on the backend. See
[Disabling Model Reasoning via Presets](../../Setup/Configuration_Files/Preset.md) for the per-backend matrix.

-----

### The Wikipedia Example Users

The wikipedia example users (`_wikipedia_multi_step_workflow`, `_wikipedia_quick_workflow`) are worker
bots, not chatbots, so they get their own collection in `Public/Configs/Endpoints/_example_wikipedia` and
`Public/Configs/Presets/<ApiPresetType>/_example_wikipedia`, kept separate from the chatbot `_example_users`:

* `Rag-Fast-Endpoint`: A fast, light model that handles its context window well,
  used to read and summarize retrieved article text. Thinking disabled.
* `Vision-Endpoint` / `Vision-Preset`: The vision model, used by the image-capable wiki workflows.

These two roles are what the `_offline_wikipedia_researcher/Wiki_*` workflows reference, so any user that runs those
workflows resolves them against its own endpoint/preset collection.

-----

### The Responder / Thinker Example Users

Two example users run a manual think-then-respond pattern and share the endpoints and presets in
`Public/Configs/Endpoints/_example_users` and `Public/Configs/Presets/<ApiPresetType>/_example_users`:

* `Responder-Endpoint` / `Responder-Preset`: Your best talker. Used to give the final response to the user after other
  models have thought about it.
* `Thinker-Endpoint` / `Thinker-Preset`: Tasked with thinking through a situation and responding with a breakdown. This
  could be a reasoning model, but it does not have to be; the workflow supplies the structure, so native reasoning is
  typically disabled.
* `Memory-Generation-Endpoint` / `Memory-Generation-Preset`: The model with the best contextual understanding for
  writing memories. If it is writing a memory, it needs to really 'get' what it is reading.
* `Vision-Endpoint` / `Vision-Preset`: Your vision model.
* `Worker-Endpoint` / `Worker-Preset`: Your workhorse. Whatever model does the best grunt work at a good speed.
