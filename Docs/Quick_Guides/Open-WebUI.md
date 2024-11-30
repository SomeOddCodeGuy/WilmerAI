## Quick Guide to Setting up Open-WebUI with WilmerAI

NOTE: Make sure that you already [set up Wilmer-Api](Wilmer-Api.md) in order to be able to connect to it. Choose
an Open WebUI friendly example user.

### Step 1: Install and run Open-WebUI.

This is harder than it sounds if you don't already have docker. There are tutorials all over for it,
but be prepared that this might be a little challenging.

Once you have it set up, you're good to go though.

### Step 2: Connect to the WilmerAI API

Once you're in Open WebUI as either an admin user, or no authentication instance, you should be able to
click on a little person icon at the top right and go to settings.

Once in settings, there should be an "Admin Settings" on the left.

Once in Admin Settings, there should be a "Connections" options.

WilmerAI can be connected to as either an OpenAI or Ollama connection, but I recommend Ollama. I find the
quality far higher. Put in the API connection info found on the console output of Wilmer if it is running

![Ollama connection example](../../Docs/Examples/Images/OW_ollama_settings.png)

You should just need to type in the IP/port like the image above, and click save at the bottom right

### Step 3: Choose WilmerAI from the dropdown at the top

Once you've saved your settings and exit the settings area, you should be able to see Wilmer as a model
in the model dropdown at the top center. If you don't, sometimes I have to reload the page to make it show up.

