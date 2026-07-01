# /Middleware/common/constants.py

VALID_NODE_TYPES = [
    "Standard", "ConversationMemory", "FullChatSummary", "RecentMemory",
    "ConversationalKeywordSearchPerformerTool", "MemoryKeywordSearchPerformerTool",
    "RecentMemorySummarizerTool", "ChatSummaryMemoryGatheringTool", "GetCurrentSummaryFromFile",
    "chatSummarySummarizer", "GetCurrentMemoryFromFile", "WriteCurrentSummaryToFileAndReturnIt",
    "SlowButQualityRAG", "QualityMemory", "PythonModule", "OfflineWikiApiFullArticle",
    "OfflineWikiApiBestFullArticle", "OfflineWikiApiTopNFullArticles", "OfflineWikiApiPartialArticle",
    "OfflineResearcherApiQuickSearch", "OfflineResearcherApiDeepResearch",
    "WorkflowLock", "CustomWorkflow", "ConditionalCustomWorkflow", "GetCustomFile", "ImageProcessor",
    "VectorMemorySearch", "SaveCustomFile", "StaticResponse", "ArithmeticProcessor", "Conditional",
    "StringConcatenator", "JsonExtractor", "TagTextExtractor", "DelimitedChunker", "ContextCompactor",
    "WebFetch", "CurlCommand", "MCPToolCall"
]
