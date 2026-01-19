export interface Settings {
  // Core chat parameters
  temperature: number
  max_tokens: number
  top_p: number

  // RAG parameters
  search_type: string
  search_base_knowledge: boolean
  search_user_knowledge: boolean
  top_k: number
  hybrid_weight: number
  system_prompt?: string

  // Query Rewriter parameters
  enable_query_rewriting: boolean
  query_rewrite_mode: 'simple' | 'with_context' | 'filtered'
  query_rewriter_prompt?: string

  // File selection parameters
  selected_files?: string[]

  // UI/Legacy parameters (for backward compatibility)
  use_rag: boolean
  use_reranker: boolean
  moderationfilter: boolean
  onlyusecontext: boolean
  embedding_model: string
  chunking_method: 'hybrid' | 'hierarchical'
}

export interface UploadedFile {
  file: File
  status: 'pending' | 'uploading' | 'processing' | 'completed' | 'error'
  id?: string
  document_id?: string
  progress?: number
  chunks_created?: number
  processing_time?: number
  chunking_method?: string
  error?: string
}

export interface ChatInterfaceProps {
  chat: any
  isExitDialogOpen: boolean
  setIsExitDialogOpen: React.Dispatch<React.SetStateAction<boolean>>
  selectedFiles?: string[]
  onClearSelectedFiles?: () => void
  onRemoveSelectedFile?: (filename: string) => void
  onNavigateToFiles?: () => void
}

export interface Citation {
  id: number
  filename: string
  content: string
  distance?: number
  chunk_index?: number
  metadata?: Record<string, any>
  document_id?: string
  source?: string
  source_type?: string
  text?: string
  chunk_method?: string
  // Web search specific fields (for agentic search results)
  title?: string
  url?: string
  snippet?: string
  supported_segments_count?: number
  supported_segments?: string[]
}

export interface Collection {
  name: string
  description: string
  entities?: number
  schema?: any
}

export interface Entity {
  id: string | number
  document_id?: string
  chunk_index?: number
  content?: string
  filename?: string
  source?: string
  department?: string
  classification_level?: string
  document_type?: string
  upload_date?: string
  metadata?: any
  [key: string]: any
}

export interface EntitiesResponse {
  entities: Entity[]
  total_count: number
  returned_count: number
  offset: number
  limit: number
  vector_fields: string[]
  collection_name: string
}

export interface SearchResult {
  id: string
  text: string
  source: string
  chunk_method: string
  distance?: number
  metadata?: any
}

export type UserFile = {
  id: string
  document_id: string
  filename: string
  file_size: number
  upload_date: string
  processed_date?: string
  chunks_created?: number
  chunk_count?: number
  chunking_method: string
  processing_status: string
  error_message?: string
  status: string
}

export type SpeechRecognition = any
export type SpeechRecognitionEvent = any
export type SpeechRecognitionErrorEvent = any
