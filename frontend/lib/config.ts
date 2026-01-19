/**
 * Frontend configuration for API endpoints
 * Used by frontend API routes (/app/api/*) to communicate with backend services
 * Components should NOT import this - they should call /api/* routes directly
 */

// Main backend API URL - used by frontend API routes only
export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

// Microservice URLs - used by frontend API routes only (not by components)
export const MILVUS_BASE_SERVICE_URL =
  process.env.NEXT_PUBLIC_MILVUS_BASE_SERVICE_URL || 'http://localhost:8003'
export const MILVUS_USER_SERVICE_URL =
  process.env.NEXT_PUBLIC_MILVUS_USER_SERVICE_URL || 'http://localhost:8004'
export const EMBEDDING_SERVICE_URL =
  process.env.NEXT_PUBLIC_EMBEDDING_SERVICE_URL || 'http://localhost:8001'
export const RERANKER_SERVICE_URL =
  process.env.NEXT_PUBLIC_RERANKER_SERVICE_URL || 'http://localhost:8002'

// API endpoints
export const API_ENDPOINTS = {
  // Authentication
  AUTH: {
    LOGIN: `${BACKEND_URL}/api/auth/login`,
    REGISTER: `${BACKEND_URL}/api/auth/register`,
    LOGOUT: `${BACKEND_URL}/api/auth/logout`,
    ME: `${BACKEND_URL}/api/auth/me`,
    VALIDATE_TOKEN: `${BACKEND_URL}/api/auth/validate-token`,
  },

  // Chat
  CHAT: {
    MODELS: `${BACKEND_URL}/api/chat/models`,
    STREAM: `${BACKEND_URL}/api/chat/stream`,
  },

  // Files
  FILES: {
    UPLOAD: `${BACKEND_URL}/api/files/upload`,
    LIST: `${BACKEND_URL}/api/files/documents`,
    DELETE: (documentId: string) =>
      `${BACKEND_URL}/api/files/documents/${documentId}`,
    STATUS: (fileId: string) => `${BACKEND_URL}/api/files/status/${fileId}`,
    SUPPORTED_FORMATS: `${BACKEND_URL}/api/files/supported-formats`,
    DOWNLOAD: (documentId: string) =>
      `${BACKEND_URL}/api/files/documents/${documentId}/download`,
  },

  // Search
  SEARCH: {
    QUERY: `${BACKEND_URL}/api/search/search`,
    SUGGESTIONS: `${BACKEND_URL}/api/search/suggestions`,
  },

  // Milvus Collections (via backend API with authentication)
  MILVUS: {
    BASE: {
      COLLECTIONS: `${BACKEND_URL}/api/milvus/base/collections`,
      ENTITIES: (collection: string) =>
        `${BACKEND_URL}/api/milvus/base/collections/${collection}/entities`,
    },
    USER: {
      COLLECTIONS: `${BACKEND_URL}/api/milvus/user/collections`,
      ENTITIES: (collection: string) =>
        `${BACKEND_URL}/api/milvus/user/collections/${collection}/entities`,
    },
  },
}

// Health check endpoints
export const HEALTH_ENDPOINTS = {
  MAIN_API: `${BACKEND_URL}/health`,
  EMBEDDING_SERVICE: `${EMBEDDING_SERVICE_URL}/health`,
  RERANKER_SERVICE: `${RERANKER_SERVICE_URL}/health`,
  MILVUS_BASE_SERVICE: `${MILVUS_BASE_SERVICE_URL}/health`,
  MILVUS_USER_SERVICE: `${MILVUS_USER_SERVICE_URL}/health`,
}

const config = {
  BACKEND_URL,
  MILVUS_BASE_SERVICE_URL,
  MILVUS_USER_SERVICE_URL,
  EMBEDDING_SERVICE_URL,
  RERANKER_SERVICE_URL,
  API_ENDPOINTS,
  HEALTH_ENDPOINTS,
}

export default config
