### **Feature Guide: WilmerAI's Offline Wikipedia Integration**

The **Offline Wikipedia Integration** feature allows WilmerAI to retrieve information from a local, offline Wikipedia
database. This is used to provide factual context to Large Language Models in Retrieval-Augmented Generation (RAG)
workflows.

This integration connects WilmerAI to the `OfflineWikipediaTextApi` project, which is a separate service that performs
vector searches on a Wikipedia data dump.

-----

### **Prerequisites and Setup**

Before using the Wikipedia nodes in a workflow, you must have
the [OfflineWikipediaTextApi](https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi) service running and accessible
on your network.

-----

## How It Works

WilmerAI's integration acts as a client to the `OfflineWikipediaTextApi` service. Specialized workflow nodes are used to
query this service.

When a workflow runs a Wikipedia node, it sends a search query to your `OfflineWikipediaTextApi` instance. The service
finds the most relevant articles, extracts the text, and returns it to the WilmerAI workflow. This retrieved text can
then be used as context for an LLM, so its response is based on the contents of the Wikipedia articles.

-----

## Configuration

To use the Wikipedia nodes, you must configure the connection to the `OfflineWikipediaTextApi` service. Add the
following settings to your WilmerAI user configuration file (e.g., `user.json`).

```json
{
  "useOfflineWikiApi": true,
  "offlineWikiApiHost": "127.0.0.1",
  "offlineWikiApiPort": 5728
}
```

Below is a breakdown of each configuration field.

* **`"useOfflineWikiApi"`**: (Boolean, Required)

    * **Purpose**: Enables or disables all offline Wikipedia nodes.
    * **Value**: Must be set to `true` to use the feature. If `false`, any Wikipedia node will be skipped and will
      return a default "no information provided" message.

* **`"offlineWikiApiHost"`**: (String, Required)

    * **Purpose**: The IP address or hostname of the machine where the `OfflineWikipediaTextApi` service is running.
    * **Value**: Defaults to `"127.0.0.1"` for a local installation.

* **`"offlineWikiApiPort"`**: (Integer, Required)

    * **Purpose**: The network port that the `OfflineWikipediaTextApi` service is listening on.
    * **Value**: Defaults to `5728`.

-----

## Using Wikipedia Nodes

After the configuration is complete, you can begin adding the Wikipedia nodes to your workflows.
