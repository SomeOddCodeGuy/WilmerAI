# /Middleware/common/constants.py

# ApiType 'type' values that identify embeddings endpoints. These cannot be used
# for text generation; LlmApiService rejects them with a clear error, and
# EmbeddingService requires one of them.
EMBEDDING_API_TYPES = ("openAIEmbeddings", "ollamaEmbeddings")

VALID_NODE_TYPES = [
    "Standard", "ConversationMemory", "FullChatSummary", "RecentMemory",
    "ConversationalKeywordSearchPerformerTool", "MemoryKeywordSearchPerformerTool",
    "RecentMemorySummarizerTool", "ChatSummaryMemoryGatheringTool", "GetCurrentSummaryFromFile",
    "chatSummarySummarizer", "GetCurrentMemoryFromFile", "GetCurrentStateDocument",
    "WriteCurrentSummaryToFileAndReturnIt",
    "SlowButQualityRAG", "QualityMemory", "PythonModule", "OfflineWikiApiFullArticle",
    "OfflineWikiApiBestFullArticle", "OfflineWikiApiTopNFullArticles", "OfflineWikiApiPartialArticle",
    "OfflineResearcherApiQuickSearch", "OfflineResearcherApiDeepResearch",
    "WorkflowLock", "CustomWorkflow", "ConditionalCustomWorkflow", "ConversationChunkProcessor",
    "GetCustomFile", "ImageProcessor",
    "VectorMemorySearch", "SaveCustomFile", "StaticResponse", "ArithmeticProcessor", "Conditional",
    "StringConcatenator", "JsonExtractor", "TagTextExtractor", "DelimitedChunker", "ContextCompactor",
    "WebFetch", "CurlCommand", "MCPToolCall"
]
