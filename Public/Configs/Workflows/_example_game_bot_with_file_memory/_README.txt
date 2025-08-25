This works best in a gaming interface that sends the names of the personas in the prompts, like SillyTavern and the like.

Before running, first open up the user and update discussionDirectory and sqlLiteDirectory. Just pick a path, or clear
them out entirely and they will default to public directory

Next open up Game_Workflow.json. There's a text file pulling node there- go make a text file and point that node to it.
File can be empty, file can have anything you want in it. This is where you can specify extra rules for the gameplay,
if you want. Each paragraph is split up and delimited by the custom delimiter. So between each paragraph would be a
"---------" unless you change that.

If you are using something like Open WebUI, I strongly recommend opening your user file and setting chatCompleteAddUserAssistant
and chatCompletionAddMissingAssistantGenerator to true. Otherwise leave them off.