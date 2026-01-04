## **The Default Example User Endpoints and Presets**

WilmerAI ships with several example users, and those come with pre-defined endpoints that are meant to be updated
with connection info from the user, so that they can be used in workflows.

While it is impossible to know what endpoints a user has available without them detailing it, it is a safe bet when
writing any workflow that the user will likely have endpoints matching these names. It is on the user to express
otherwise.

#### Endpoints

The endpoints for the example users can be found in `Public/Configs/Endpoints/_example_users`

* `Coding-Endpoint`: Your best coding model. This is the main problem solver and coder
* `Coding-Fast-Endpoint`: A fast and light coding model. This generally gets tasked with quick iterations, double
  checking, etc.
* `General-Endpoint`: Your best generalist model.
* `General-Fast-Endpoint`: A fast and light generalist model. This gets tasked with quick iterations, double checking,
  etc.c
* `General-Rag-Endpoint`: Your model that has the best context understanding. This gets used for heavy RAG tasks,
  meaning large amounts of text with a high expectation of it to use that text properly.
* `General-Rag-Fast-Endpoint`: A fast and light RAG model. Whatever the smallest and fastest model you have that handles
  its context window well, as it will be given large amounts of text and expected to use that text properly.
* `Vision-Endpoint`: Your vision model. Used with the workflows that have an Image Processing node at the start. None of
  the example users do by default, but you can swap the workflows easily to include them
* `Memory-Generation-Endpoint`: Model that has the best contextual understanding but also does RAG well. If its writing
  a memory, it needs to really 'get' what it's reading and what was happening/being said.
* `Responder-Endpoint`: Your best talker. Some example users use this to give the final response to the user, after
  other models have thought about it.
* `Thinker-Endpoint`: The model that is tasked, by some example users, to think through a situation and respond with a
  breakdown of things. This could be a reasoning model, but it doesn't have to be. Socg doesn't use reasoning models, or
  if he does he disables the reasoning. That's what workflows are for.
* `Worker-Endpoint`: Your workhorse. Whatever model does the best grunt work at a good speed.

#### Presets

* `Coding-Preset`: A preset configured for code generation with your best coding model.
* `Coding-Fast-Preset`: A preset configured for quick coding tasks with a fast and light model.
* `General-Preset`: A preset for general purpose work with your best generalist model.
* `General-Fast-Preset`: A preset for quick general tasks with a fast and light model.
* `General-Rag-Preset`: A preset for heavy RAG tasks requiring good context understanding.
* `General-Rag-Fast-Preset`: A preset for quick RAG tasks with a fast model that handles context well.
* `General-Reasoning-Preset`: A preset for reasoning/thinking models.
* `Memory-Generation-Preset`: A preset for memory generation tasks requiring good contextual understanding.
* `Responder-Preset`: A preset for creative responses, typically with higher temperature (0.8-1.2).
* `Thinker-Preset`: A preset for models tasked with thinking through situations and providing breakdowns.
* `Vision-Preset`: A preset configured for vision models.
* `Worker-Preset`: A preset for general purpose workhorse tasks.
* `Worker-LowTemp-Preset`: A preset for tasks requiring near deterministic responses.