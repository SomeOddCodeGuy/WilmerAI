## The `Offline Wikipedia` Nodes

The Offline Wikipedia nodes act as a tool for querying a local `OfflineWikipediaTextApi` instance. They allow your
workflow to search for articles by topic and inject the text content as a variable for use in subsequent nodes, such as
providing factual context to an LLM.

-----

### **JSON Configuration**

All Wikipedia nodes are configured within your workflow's JSON file. The specific behavior is determined by the `type`
field.

#### **Complete Example**

This example uses the `OfflineWikiApiTopNFullArticles` type to demonstrate all possible configuration fields.

```json
{
  "title": "Fetch Top Articles on AI",
  "agentName": "AIResearch",
  "type": "OfflineWikiApiTopNFullArticles",
  "promptToSearch": "The history of artificial intelligence",
  "percentile": 0.5,
  "num_results": 20,
  "top_n_articles": 3
}
```

#### **Common Fields**

These fields are available for all Offline Wikipedia node types.

* `"title"`: **(String, Optional)**

    * **Purpose**: A user-friendly name for this node instance, used for logging and workflow readability.
    * **Example**: `"Querying the offline wikipedia api"`

* `"agentName"`: **(String, Required)**

    * **Purpose**: Defines the name for the output variable. The text returned by the node will be stored in a workflow
      variable based on this name.
    * **Example**: If `agentName` is `"AIResearch"`, the output can be accessed in subsequent nodes using the variable
      `{AIResearch}`.

* `"type"`: **(String, Required)**

    * **Purpose**: Specifies which Wikipedia search handler to use. Each type has a distinct behavior and output format.
    * **Value**: Must be one of the types listed in the "Node Types and Behaviors" section below.

* `"promptToSearch"`: **(String, Required)**

    * **Purpose**: The search query or topic to look for in the Wikipedia database.
    * **Value**: A string that can contain WilmerAI variables (e.g., `{userQuestion}`), which will be resolved before
      the search is executed.

-----

### **Node Types and Behaviors**

This section details the behavior and specific configuration for each available `type`.

#### `OfflineWikiApiBestFullArticle`

This node performs a broad search and then uses a scoring algorithm to identify and return only the single best-matching
full article for the query.

* **JSON Example**
  ```json
  {
    "title": "Get Best Article on Alan Turing",
    "agentName": "TuringArticle",
    "type": "OfflineWikiApiBestFullArticle",
    "promptToSearch": "Who was Alan Turing?"
  }
  ```
* **Output Format**: A single string containing the full text of the highest-scoring article.

#### `OfflineWikiApiTopNFullArticles`

This node returns a specified number of the most relevant full articles. It is highly configurable and useful for
gathering a wide range of context on a topic.

* **JSON Example**
  ```json
  {
    "title": "Get top 3 articles on Roman History",
    "agentName": "RomanHistory",
    "type": "OfflineWikiApiTopNFullArticles",
    "promptToSearch": "The fall of the Roman Republic",
    "top_n_articles": 3
  }
  ```
* **Output Format**: A single string containing all returned articles, formatted with titles and separated by a
  delimiter.
  ```
  Title: Roman Republic
  The Roman Republic was the era of classical Roman civilization...

  --- END ARTICLE ---

  Title: Julius Caesar
  Gaius Julius Caesar was a Roman general and statesman...
  ```

#### `OfflineWikiApiPartialArticle`

This node retrieves the single best-matching article for the query but returns only its summary (typically the first
paragraph). This is useful for conserving context space when only a brief overview is needed.

* **JSON Example**
  ```json
  {
    "title": "Get Photosynthesis Summary",
    "agentName": "PhotoSummary",
    "type": "OfflineWikiApiPartialArticle",
    "promptToSearch": "What is photosynthesis?"
  }
  ```
* **Output Format**: A single string containing the summary text of the best-matching article.

#### `OfflineWikiApiFullArticle`

This node retrieves the first full article returned by the search query. It uses a more direct search method than
`OfflineWikiApiBestFullArticle`.

* **JSON Example**
  ```json
  {
    "title": "Get First-Result Article",
    "agentName": "FirstResult",
    "type": "OfflineWikiApiFullArticle",
    "promptToSearch": "The geography of Antarctica"
  }
  ```
* **Output Format**: A single string containing the full text of the first search result.

-----

### **Advanced Configuration**

The `OfflineWikiApiTopNFullArticles` node type supports optional parameters to fine-tune its search behavior.

* `"percentile"`: **(Float, Optional)**

    * **Purpose**: Sets the minimum relevance score (from 0.0 to 1.0) for an article to be included in the initial
      candidate pool. Higher values make the search stricter.
    * **Default**: `0.5`

* `"num_results"`: **(Integer, Optional)**

    * **Purpose**: The size of the initial candidate pool from which the top articles will be selected.
    * **Default**: `10`

* `"top_n_articles"`: **(Integer, Optional)**

    * **Purpose**: The final number of articles to select from the candidate pool and return. If a **negative value** is
      used (e.g., `-3`), the articles will be returned in ascending order of relevance (least relevant first). This can
      be useful to ensure the most relevant information is preserved when an LLM truncates long context from the
      beginning.
    * **Default**: `3`