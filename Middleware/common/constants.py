# WilmerAI/Middleware/common/constants.py
VALID_NODE_TYPES = [
    "Standard", "ConversationMemory", "FullChatSummary", "RecentMemory",
    "ConversationalKeywordSearchPerformerTool", "MemoryKeywordSearchPerformerTool",
    "RecentMemorySummarizerTool", "ChatSummaryMemoryGatheringTool", "GetCurrentSummaryFromFile",
    "chatSummarySummarizer", "GetCurrentMemoryFromFile", "WriteCurrentSummaryToFileAndReturnIt",
    "SlowButQualityRAG", "QualityMemory", "PythonModule", "OfflineWikiApiFullArticle",
    "OfflineWikiApiBestFullArticle", "OfflineWikiApiTopNFullArticles", "OfflineWikiApiPartialArticle",
    "WorkflowLock", "CustomWorkflow", "ConditionalCustomWorkflow", "GetCustomFile", "ImageProcessor"
] 