### **LLM Assisted Workflow Generation In WilmerAI**

Because workflows in Wilmer are written in json format, and because there is extensive documentation now surrounding
those workflows, it's becoming more feasible to generate workflows using an LLM than in the past. Because of that,
I have begun to focus my efforts on solid documentation surrounding how to do so.

This directory contains much of the information that you'd need to do it.

#### Example Creating Wikipedia Feature

The below prompt is one I have used for several recent workflows, using either GLM 4.5 q8_0, or Gemini Pro 2.5
Obviously, Gemini is going to give me be better results.

This example prompt is exactly what I'd use to create a wikipedia workflow. The actual prompt would replace
each `#` comment with the .md file I reference.

```text
I have the following project:
<doc>
# Put the User_Documentation README.md here
</doc>

With the following features:
<features>
# User_Documentation/Setup/Workflow_Details/Workflows.md

-------

# User_Documentation/Setup/Workflow_Details/Workflow_Variables.md

-------

# User_Documentation/Setup/Workflow_Details/Workflow_Features.md

-------

# User_Documentation/Core_Features/Offline_Wikipedia_Support.md
</features>

This project has the following nodes available:
<workflow_nodes>
# User_Documentation/Setup/Workflow_Details/Nodes/Offline_Wikipedia.md

-------

# User_Documentation/Setup/Workflow_Details/Workflow_Nodes.md
</workflow_nodes>

And the following example guide on how to write a wikipedia workflow:
<example_guide>
# User_Documentation/LLM_Assisted_Workflow_Generation/Example_Guide_Wikipedia_Search.md
</example_guide>

And finally, here are some recommended prompting methodologies that the project maintainer, Socg,
tends to use:
<wilmer_prompting_methodologies>
# User_Documentation/LLM_Assisted_Workflow_Generation/Workflow_Prompting_Methodologies_Socg.md
</wilmer_prompting_methodologies>

Along with this, here are the default endpoints and presets that are generally available to use:
<endpoints_and_presets>
# User_Documentation/LLM_Assisted_Workflow_Generation/Default_Endpoints_And_Presets
</endpoints_and_presets>

I'd like a workflow that will search wikipedia for whatever I'm asking about. I only want it to do a single
article- looking for the best one and then using that to answer me.

Before we begin, please first determine if any other documentation is needed, and ask at least 3 clarifying
questions about the request and/or your expected output.
```

#### Breakdown of the Example Prompt

The above example prompt is tailored towards making a new wikipedia feature, which is what we want to
create for this example. If you wanted another feature, you'd swap out or simply remove the wikipedia
specific items, such as the `Offline_Wikipedia_Support`, `Example_Guide_Wikipedia_Search` and `Offline_Wikipedia`

The example prompt gives the LLM multiple pieces of valuable information:

* A high level understanding of the project with the `README.md`. What is Wilmer? What does it do?
* A high level understanding of workflows with `workflows.md`
* A high level understanding of workflow variables, and their limitations, with `workflow_variables.md`
* A high level understanding of all features available within Wilmer, and what documents to ask for, in
  workflow_features.md
* A detailed understanding of the offline Wikipedia feature of Wilmer with `Offline_Wikipedia_Support.md`,
  which we include specially since we know we want this.

By telling the LLM the above, we give it a foundation to understand exactly what we're talking about, and what
expectations we have. It now knows we want workflows, that workflows have nodes and variables, what tools are
available to get the job done, and detailed information on the feature to hit an offline wikipedia api.

Next, we give it the nodes to work with. There are 2 levels of information we can give the LLM about the nodes:

* `User_Documentation/Setup/Workflow_Details/Nodes/` gives detailed documentation on every usable node in Wilmer.
  These documents should contain exhaustive information on each node. You could give every one of them to your LLM,
  but you'd likely eat up a lot of context that way.
* `User_Documentation/Setup/Workflow_Details/Workflow_Nodes.md` and
  `User_Documentation/Setup/Workflow_Details/Worklow_Nodes_Memories.md` give high level overviews of all the available
  memory and non-memory nodes available. These documents should be sufficient to give an LLM an idea of what nodes
  exist and how to use them in a workflow.

In order to preserve context, we decide to give it the detailed node information for the feature we care about:
offline wikipedia. Then we give it the high level overview of the other nodes with `Workflow_Nodes.md`. We don't care
about memories in this workflow, so we don't bother giving that.

Next, we give it the `Example_Guide_Wikipedia_Search.md`, which helps give the LLM a high level understanding of some
of the prompting strategies that have been successful with Wilmer in the past for this type of work.
Sometimes LLMs tend to fail at prompt engineering, and especially in something it hasn't seen before like Wilmer,
and will cut corners in some places or not be descriptive enough in others. This will help steer it in the right
direction.

To help with that regard, the final item we supply is the `Workflow_Prompting_Methodologies_Socg.md`, which is a
forensic breakdown of how Socg appears to write prompts when using Wilmer.

Along with all of that information on how to construct the prompt, we hand over a list of the default endpoints
and presets, so it knows what to put on each node.

Finally, we give clear instructions of what we want, exactly, and then ask it to ask some questions.

Once you answer the questions, you should get a pretty good result.


#### Generic Example Prompt

```text
I have the following project:
<doc>
# Put the User_Documentation README.md here
</doc>

With the following features:
<features>
# User_Documentation/Setup/Workflow_Details/Workflows.md

-------

# User_Documentation/Setup/Workflow_Details/Workflow_Variables.md

-------

# User_Documentation/Setup/Workflow_Details/Workflow_Features.md
</features>

This project has the following nodes available:
<workflow_nodes>
# User_Documentation/Setup/Workflow_Details/Workflow_Nodes.md
</workflow_nodes>

And finally, here are some recommended prompting methodologies that the project maintainer, Socg,
tends to use:
<wilmer_prompting_methodologies>
# User_Documentation/LLM_Assisted_Workflow_Generation/Workflow_Prompting_Methodologies_Socg.md
</wilmer_prompting_methodologies>

Along with this, here are the default endpoints and presets that are generally available to use:
<endpoints_and_presets>
# User_Documentation/LLM_Assisted_Workflow_Generation/Default_Endpoints_And_Presets
</endpoints_and_presets>

I'd like a workflow that...

Before we begin, please first determine if any other documentation is needed, and ask at least 3 clarifying
questions about the request and/or your expected output.
```


#### Example Code Written With This Guide

Using the exact steps outlined in this guide, except dropping the wikipedia references in the example prompt, I
generated the recursive coding poc workflow in _common folder. I'll be toying with it over the course of the next
couple of weeks, but so far it seems to work alright.

I'll continue to improve this as we go.