This user is intended to be used with a frontend that specifies the name of each user who is speaking; especially if
it adds the assistant name to the generation prompt. SillyTavern does this by default, other front ends may as well.

Before running, first open up the user and update discussionDirectory and sqlLiteDirectory. Just pick a path, or clear
them out entirely and they will default to public directory

Next, open up the Memory_Vector_Workflow. Make 2 text files somewhere- one to act as a persona card for you, and
one to act as a persona card for your assistant. Change the two file pullers in Nodes 2 and 3 to reflect.

If you are using something like Open WebUI, I strongly recommend opening your user file and setting chatCompleteAddUserAssistant
and chatCompletionAddMissingAssistantGenerator to true. Otherwise leave them off for ST and the like.