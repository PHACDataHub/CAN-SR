'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Database,
  Eye,
  RefreshCw,
  Search,
  FileText,
  Building2,
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react'
import { Input } from '@/components/ui/input'
import type {
  Collection,
  Entity,
  EntitiesResponse,
  SearchResult,
} from './types'
import { getAuthToken } from '@/lib/auth'

interface MilvusViewerProps {
  trigger?: React.ReactNode
}

export function MilvusViewer({ trigger }: MilvusViewerProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [baseCollections, setBaseCollections] = useState<Collection[]>([])
  const [userCollections, setUserCollections] = useState<Collection[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('base')
  const [selectedCollection, setSelectedCollection] = useState<string | null>(
    null,
  )
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [selectedCollectionType, setSelectedCollectionType] = useState<
    'base' | 'user'
  >('base')
  const [entities, setEntities] = useState<Entity[]>([])
  const [entitiesLoading, setEntitiesLoading] = useState(false)
  const [entitiesData, setEntitiesData] = useState<EntitiesResponse | null>(
    null,
  )
  const [currentPage, setCurrentPage] = useState(0)
  const [pageSize, setPageSize] = useState(10)
  const [renderKey, setRenderKey] = useState(0)
  const [allEntities, setAllEntities] = useState<Entity[]>([]) // Store all entities for frontend pagination

  const fetchCollections = async (forceRefresh = false) => {
    setLoading(true)
    try {
      const token = getAuthToken()
      const headers = {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      }

      // Add cache-busting parameter when force refreshing
      const cacheBuster = forceRefresh ? `?_t=${Date.now()}` : ''

      const [baseResponse, userResponse] = await Promise.all([
        fetch(`/api/milvus/base/collections${cacheBuster}`, { headers }),
        fetch(`/api/milvus/user/collections${cacheBuster}`, { headers }),
      ])

      if (!baseResponse.ok || !userResponse.ok) {
        throw new Error('Failed to fetch collections')
      }

      const [baseData, userData] = await Promise.all([
        baseResponse.json(),
        userResponse.json(),
      ])

      setBaseCollections(baseData.collections || [])
      setUserCollections(userData.collections || [])
    } catch (error) {
      console.error('Error fetching collections:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSearch = async (collectionType: 'base' | 'user') => {
    if (!searchQuery.trim()) return

    setSearchLoading(true)
    try {
      const token = getAuthToken()
      const search_type = collectionType === 'base' ? 'base_only' : 'user_only'

      const response = await fetch('/api/search', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: searchQuery,
          search_type,
          top_k: 10,
          hybrid_weight: 0.5,
          chunking_method: 'all',
        }),
      })

      if (!response.ok) {
        throw new Error('Search failed')
      }

      const data = await response.json()
      setSearchResults(data.results || [])
    } catch (error) {
      console.error('Error searching collection:', error)
      setSearchResults([])
    } finally {
      setSearchLoading(false)
    }
  }

  const loadAllEntities = async (
    collectionName: string,
    collectionType: 'base' | 'user',
  ) => {
    setEntitiesLoading(true)

    try {
      const token = getAuthToken()
      const apiPath =
        collectionType === 'base'
          ? `/api/milvus/base/collections/${collectionName}/entities`
          : `/api/milvus/user/collections/${collectionName}/entities`

      // Fetch all entities with a large limit (Milvus max is usually 16384)
      const url = `${apiPath}?limit=16384&offset=0`

      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })

      if (!response.ok) {
        throw new Error(
          `Failed to fetch entities: ${response.status} ${response.statusText}`,
        )
      }

      const data = await response.json()

      // Store all entities for frontend pagination
      const fetchedEntities = data.entities || []
      setAllEntities(fetchedEntities)

      // Create mock entitiesData with correct total count
      const mockEntitiesData = {
        ...data,
        total_count: fetchedEntities.length, // Use actual fetched count
        returned_count: Math.min(pageSize, fetchedEntities.length),
        offset: 0,
        limit: pageSize,
        vector_fields: data.vector_fields || [],
        collection_name: collectionName,
        entities: fetchedEntities.slice(0, pageSize), // Show first page
      }

      setEntitiesData(mockEntitiesData)
      setEntities(fetchedEntities.slice(0, pageSize))
      setCurrentPage(0) // Reset to first page
      setRenderKey((prev) => prev + 1)
    } catch (error) {
      console.error('Error fetching entities:', error)
      setEntities([])
      setEntitiesData(null)
      setAllEntities([])
    } finally {
      setEntitiesLoading(false)
    }
  }

  const updateDisplayedEntities = (page: number, size: number) => {
    const startIndex = page * size
    const endIndex = startIndex + size
    const pageEntities = allEntities.slice(startIndex, endIndex)

    if (entitiesData) {
      const updatedData = {
        ...entitiesData,
        returned_count: pageEntities.length,
        offset: startIndex,
        limit: size,
        entities: pageEntities,
      }
      setEntitiesData(updatedData)
      setEntities(pageEntities)
      setRenderKey((prev) => prev + 1)
    }
  }

  const handleCollectionClick = (
    collectionName: string,
    collectionType: 'base' | 'user',
  ) => {
    setSelectedCollection(collectionName)
    setSelectedCollectionType(collectionType)
    setCurrentPage(0)
    setEntities([]) // Clear previous entities
    setEntitiesData(null) // Clear previous data
    setAllEntities([]) // Clear all entities
    setRenderKey(0) // Reset render key
    loadAllEntities(collectionName, collectionType) // Load all entities for frontend pagination
  }

  const handlePageChange = (newPage: number) => {
    if (allEntities.length > 0) {
      setCurrentPage(newPage)
      updateDisplayedEntities(newPage, pageSize)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchCollections(true) // Force refresh when opening
    }
  }, [isOpen])

  // Auto-refresh collections when switching tabs
  useEffect(() => {
    if (isOpen && !selectedCollection) {
      fetchCollections(true)
    }
  }, [activeTab, isOpen, selectedCollection])

  // Periodic auto-refresh for collections when viewer is open (every 30 seconds)
  useEffect(() => {
    if (isOpen && !selectedCollection) {
      const interval = setInterval(() => {
        fetchCollections(true)
      }, 30000) // 30 seconds
      return () => clearInterval(interval)
    }
  }, [isOpen, selectedCollection])

  const defaultTrigger = (
    <Button
      variant="outline"
      size="sm"
      className="w-full border-gray-300 hover:bg-gray-100 hover:text-gray-900"
    >
      <Database className="mr-2 h-4 w-4" />
      View Milvus Collections
    </Button>
  )

  const formatNumber = (num: number | undefined) => {
    if (num === undefined || num === null || isNaN(num)) {
      return '0'
    }
    return new Intl.NumberFormat().format(num)
  }

  const formatDescription = (description: string) => {
    if (!description) return description

    const timestampMatch = description.match(
      /Created (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?)/,
    )

    if (timestampMatch) {
      try {
        const timestamp = new Date(timestampMatch[1])
        const formattedDate = timestamp.toLocaleDateString('en-US', {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })
        return description.replace(
          timestampMatch[0],
          `Created ${formattedDate}`,
        )
      } catch (error) {
        console.error('Error formatting description:', error)
        return description
      }
    }

    return description
  }

  const CollectionCard = ({
    collection,
    type,
  }: {
    collection: Collection
    type: 'base' | 'user'
  }) => (
    <Card
      className="group mb-4 cursor-pointer overflow-hidden border-gray-200 transition-shadow duration-200 hover:border-gray-300 hover:shadow-md"
      onClick={() => handleCollectionClick(collection.name, type)}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div
              className={`rounded-lg p-2 ${type === 'base' ? 'bg-slate-100 text-slate-600' : 'bg-emerald-100 text-emerald-600'}`}
            >
              {type === 'base' ? (
                <Building2 className="h-5 w-5" />
              ) : (
                <FileText className="h-5 w-5" />
              )}
            </div>
            <div>
              <CardTitle className="flex items-center gap-2 text-base font-semibold">
                <span className="font-mono">{collection.name}</span>
              </CardTitle>
              <CardDescription className="mt-1 text-xs text-gray-500">
                {formatDescription(collection.description)}
              </CardDescription>
            </div>
          </div>
          <div className="flex flex-col items-end">
            <Badge
              variant={type === 'base' ? 'default' : 'secondary'}
              className={`px-2.5 py-1 text-xs ${type === 'base' ? 'bg-slate-100 text-slate-700' : 'bg-emerald-100 text-emerald-700'}`}
            >
              {formatNumber(collection.entities)} entities
            </Badge>
            <div className="mt-2 text-slate-400 transition-colors group-hover:text-slate-600">
              <Eye className="h-4 w-4" />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )

  const MetadataItem = ({
    label,
    value,
    isMono = false,
  }: {
    label: string
    value: string
    isMono?: boolean
  }) => (
    <div>
      <span className="block text-[10px] font-medium tracking-wider text-gray-400 uppercase">
        {label}
      </span>
      <div
        className={`truncate text-sm text-gray-700 ${isMono ? 'font-mono' : ''}`}
      >
        {value}
      </div>
    </div>
  )

  const EntitiesView = () => {
    if (!selectedCollection || !entitiesData) return null

    return (
      <div className="space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSelectedCollection(null)
              setSelectedCollectionType('base')
              setEntities([])
              setEntitiesData(null)
              setCurrentPage(0)
            }}
            className="flex items-center gap-1 text-gray-700 hover:bg-slate-50 hover:text-slate-600"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Collections
          </Button>
          <div className="text-sm font-medium text-gray-600">
            {allEntities.length > 0
              ? `Showing ${currentPage * pageSize + 1}-${Math.min((currentPage + 1) * pageSize, allEntities.length)} of ${allEntities.length} entities`
              : `No entities found`}
          </div>
        </div>

        {entitiesLoading ? (
          <div className="rounded-lg border bg-gray-50 py-12 text-center">
            <RefreshCw className="mx-auto mb-4 h-10 w-10 animate-spin text-slate-500" />
            <p className="font-medium text-gray-600">Loading entities...</p>
          </div>
        ) : entities.length > 0 ? (
          <div key={`entities-container-${renderKey}`} className="space-y-4">
            {entities.map((entity, index) => (
              <Card
                key={`${selectedCollection}-page${currentPage}-entity${entity.id}-idx${index}`}
                className="overflow-hidden border-gray-200 bg-white shadow-sm transition-all hover:border-gray-300 hover:shadow-md"
              >
                <div className="flex items-center justify-between border-b bg-gray-50 px-4 py-2 text-sm">
                  <div className="flex items-center gap-2 font-mono">
                    <Badge
                      variant="outline"
                      className="bg-white px-2 py-0.5 text-xs font-semibold"
                    >
                      ID: {entity.id}
                    </Badge>
                    <Badge
                      variant="outline"
                      className="bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                    >
                      Page {currentPage + 1}
                    </Badge>
                    {entity.chunk_index !== undefined && (
                      <Badge
                        variant="secondary"
                        className="px-2 py-0.5 text-xs"
                      >
                        Chunk {entity.chunk_index}
                      </Badge>
                    )}
                  </div>
                  {entity.filename && (
                    <div className="flex items-center gap-1.5 text-xs text-gray-600">
                      <FileText className="h-3.5 w-3.5 text-gray-400" />
                      <span className="max-w-[250px] truncate font-medium">
                        {entity.filename}
                      </span>
                    </div>
                  )}
                </div>

                <div className="p-4">
                  <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
                    {entity.source && (
                      <MetadataItem label="Source" value={entity.source} />
                    )}
                    {entity.department && (
                      <MetadataItem
                        label="Department"
                        value={entity.department}
                      />
                    )}
                    {entity.classification_level && (
                      <MetadataItem
                        label="Classification"
                        value={entity.classification_level}
                      />
                    )}
                    {entity.document_type && (
                      <MetadataItem
                        label="Document Type"
                        value={entity.document_type}
                      />
                    )}
                    {entity.upload_date && (
                      <MetadataItem
                        label="Upload Date"
                        value={new Date(entity.upload_date).toLocaleString()}
                      />
                    )}
                  </div>

                  <div className="grid grid-cols-1 items-start gap-x-6 border-t pt-4 lg:grid-cols-2">
                    <div>
                      {entity.content && (
                        <div>
                          <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-800">
                            Content
                            <Badge
                              variant="outline"
                              className="text-xs font-normal"
                            >
                              text
                            </Badge>
                          </h4>
                          <div className="hide-scrollbar max-h-80 overflow-y-auto rounded-lg border bg-gray-50/50 p-3 text-xs shadow-inner">
                            <pre className="font-sans whitespace-pre-wrap">
                              {entity.content}
                            </pre>
                          </div>
                        </div>
                      )}
                    </div>

                    <div>
                      {entity.metadata &&
                        Object.keys(entity.metadata).length > 0 &&
                        typeof entity.metadata === 'object' && (
                          <div>
                            <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-800">
                              Additional Metadata
                              <Badge
                                variant="outline"
                                className="text-xs font-normal"
                              >
                                json
                              </Badge>
                            </h4>
                            <div className="max-h-80 overflow-x-auto rounded-lg border bg-gray-800 p-3 font-mono text-[11px] text-gray-200">
                              <pre className="whitespace-pre-wrap">
                                {JSON.stringify(entity.metadata, null, 2)}
                              </pre>
                            </div>
                          </div>
                        )}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        ) : allEntities.length === 0 ? (
          <div className="rounded-lg border bg-gray-50 py-16 text-center">
            <div className="mb-2 text-gray-400">
              <Database className="mx-auto h-12 w-12 opacity-50" />
            </div>
            <p className="text-lg text-gray-500">
              No entities found in this collection
            </p>
          </div>
        ) : (
          <div className="rounded-lg border bg-gray-50 py-16 text-center">
            <div className="mb-2 text-gray-400">
              <Database className="mx-auto h-12 w-12 opacity-50" />
            </div>
            <p className="text-lg text-gray-500">
              No entities found on this page
            </p>
            <p className="mt-2 text-sm text-gray-400">
              This shouldn&apos;t happen with frontend pagination. Please
              refresh the collection.
            </p>
          </div>
        )}
      </div>
    )
  }

  const PaginationControls = () => {
    if (!selectedCollection || !entitiesData || allEntities.length === 0)
      return null
    const totalPages = Math.ceil(allEntities.length / pageSize)

    return (
      <div className="flex w-full flex-col space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500">Show:</span>
            <div className="flex overflow-hidden rounded-md border">
              {[10, 20, 50].map((size) => (
                <button
                  key={size}
                  onClick={() => {
                    setPageSize(size)
                    const newPage = Math.floor((currentPage * pageSize) / size)
                    setCurrentPage(newPage)
                    updateDisplayedEntities(newPage, size)
                  }}
                  className={`px-2.5 py-1 text-xs font-medium ${
                    pageSize === size
                      ? 'bg-slate-600 text-white'
                      : 'bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
            <span className="text-sm text-gray-500">entities per page</span>
          </div>

          <div className="text-sm text-gray-500">
            {totalPages > 0
              ? `Page ${currentPage + 1} of ${totalPages}`
              : 'No pages available'}
          </div>
        </div>

        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handlePageChange(currentPage - 1)}
            disabled={currentPage === 0 || totalPages <= 1}
            className="flex items-center gap-1 bg-white hover:bg-slate-50 hover:text-slate-600"
          >
            <ChevronLeft className="h-4 w-4" />
            Previous
          </Button>

          {totalPages > 1 && (
            <div className="mx-2 flex items-center gap-1">
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum: number
                if (totalPages <= 5) {
                  pageNum = i
                } else if (currentPage < 2) {
                  pageNum = i
                } else if (currentPage >= totalPages - 3) {
                  pageNum = totalPages - 5 + i
                } else {
                  pageNum = currentPage - 2 + i
                }

                if (pageNum < 0 || pageNum >= totalPages) return null

                return (
                  <Button
                    key={pageNum}
                    variant={pageNum === currentPage ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => handlePageChange(pageNum)}
                    className={`h-8 w-8 p-0 ${pageNum === currentPage ? 'bg-slate-600 text-white hover:bg-slate-700' : 'bg-white hover:bg-slate-50 hover:text-slate-600'}`}
                  >
                    {pageNum + 1}
                  </Button>
                )
              })}
            </div>
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={() => handlePageChange(currentPage + 1)}
            disabled={currentPage >= totalPages - 1 || totalPages <= 1}
            className="flex items-center gap-1 bg-white hover:bg-slate-50 hover:text-slate-600"
          >
            Next
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    )
  }

  const SearchSection = ({ type }: { type: 'base' | 'user' }) => (
    <div className="mt-6 space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 transform text-gray-400" />
          <Input
            placeholder={`Search ${type} knowledge...`}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="focus:ring-opacity-50 border-gray-300 pl-10 focus:border-slate-300 focus:ring focus:ring-slate-200"
            onKeyDown={(e) => e.key === 'Enter' && handleSearch(type)}
          />
        </div>
        <Button
          onClick={() => handleSearch(type)}
          disabled={searchLoading || !searchQuery.trim()}
          size="sm"
          className={
            type === 'base'
              ? 'bg-slate-600 hover:bg-slate-700'
              : 'bg-emerald-600 hover:bg-emerald-700'
          }
        >
          {searchLoading ? (
            <RefreshCw className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
        </Button>
      </div>

      {searchResults.length > 0 && (
        <div className="hide-scrollbar max-h-96 space-y-3 overflow-y-auto rounded-md border bg-gray-50 p-4">
          <h4 className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <Search className="h-4 w-4 text-gray-500" />
            Search Results ({searchResults.length})
          </h4>
          {searchResults.map((result, index) => (
            <Card
              key={index}
              className="border-gray-200 p-4 transition-all hover:border-gray-300"
            >
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Badge variant="outline" className="bg-white text-xs">
                    {result.chunk_method}
                  </Badge>
                  {result.distance && (
                    <span className="text-xs text-gray-500">
                      Distance: {result.distance.toFixed(3)}
                    </span>
                  )}
                </div>
                <p className="line-clamp-3 rounded border bg-white p-2 text-sm text-gray-800">
                  {result.text}
                </p>
                <p className="flex items-center gap-1 truncate text-xs text-gray-500">
                  <FileText className="h-3 w-3" />
                  Source: {result.source}
                </p>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <div>
      <div onClick={() => setIsOpen(!isOpen)}>{trigger || defaultTrigger}</div>

      {isOpen && (
        <Card className="fixed top-[50%] left-[50%] z-50 flex h-[90vh] w-[90vw] max-w-[1400px] -translate-x-1/2 -translate-y-1/2 transform flex-col shadow-xl">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-lg font-medium">
                <Database className="h-5 w-5" />
                {selectedCollection
                  ? `${selectedCollection} - Entities (${Math.min((currentPage + 1) * pageSize, allEntities.length)} of ${allEntities.length})`
                  : 'Milvus Collections Viewer'}
              </CardTitle>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsOpen(false)}
                className="h-8 w-8 p-0 hover:bg-gray-100 hover:text-gray-700"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            <CardDescription className="text-sm text-gray-500">
              Browse vector database collections
            </CardDescription>
          </CardHeader>
          <CardContent className="hide-scrollbar flex-1 overflow-y-auto p-4">
            {selectedCollection ? (
              <EntitiesView />
            ) : (
              <Tabs
                value={activeTab}
                onValueChange={setActiveTab}
                className="flex h-full w-full flex-col"
              >
                <div className="mb-4 flex items-center justify-between">
                  <TabsList className="grid w-full grid-cols-2 rounded-lg bg-gray-100 p-1">
                    <TabsTrigger
                      value="base"
                      className="flex items-center gap-2 data-[state=active]:bg-white data-[state=active]:shadow-sm"
                    >
                      <Building2 className="h-4 w-4 text-slate-600" />
                      Base Knowledge
                    </TabsTrigger>
                    <TabsTrigger
                      value="user"
                      className="flex items-center gap-2 data-[state=active]:bg-white data-[state=active]:shadow-sm"
                    >
                      <FileText className="h-4 w-4 text-emerald-600" />
                      My Documents
                    </TabsTrigger>
                  </TabsList>
                </div>

                <TabsContent value="base" className="mt-0 flex-1">
                  <div className="flex h-full flex-col rounded-lg border bg-white p-4">
                    <div className="mb-4 flex items-center gap-2 border-b pb-2 text-sm text-gray-600">
                      <Building2 className="h-5 w-5 text-slate-600" />
                      <span className="font-medium">
                        Government of Canada Knowledge Base
                      </span>
                    </div>

                    <div className="hide-scrollbar flex-1 space-y-4 overflow-y-auto pr-1">
                      {loading ? (
                        <div className="py-8 text-center">
                          <RefreshCw className="mx-auto mb-2 h-8 w-8 animate-spin text-slate-500" />
                          <p className="text-gray-600">
                            Loading collections...
                          </p>
                        </div>
                      ) : baseCollections.length > 0 ? (
                        <>
                          {baseCollections.map((collection, index) => (
                            <CollectionCard
                              key={index}
                              collection={collection}
                              type="base"
                            />
                          ))}
                          <SearchSection type="base" />
                        </>
                      ) : (
                        <div className="rounded-lg border bg-gray-50 py-8 text-center">
                          <Database className="mx-auto mb-2 h-10 w-10 text-gray-300" />
                          <p className="text-gray-500">
                            No base collections found
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="user" className="mt-0 flex-1">
                  <div className="flex h-full flex-col rounded-lg border bg-white p-4">
                    <div className="mb-4 flex items-center gap-2 border-b pb-2 text-sm text-gray-600">
                      <FileText className="h-5 w-5 text-emerald-600" />
                      <span className="font-medium">
                        Your Personal Document Collections
                      </span>
                    </div>

                    <div className="hide-scrollbar flex-1 space-y-4 overflow-y-auto pr-1">
                      {loading ? (
                        <div className="py-8 text-center">
                          <RefreshCw className="mx-auto mb-2 h-8 w-8 animate-spin text-emerald-500" />
                          <p className="text-gray-600">
                            Loading collections...
                          </p>
                        </div>
                      ) : userCollections.length > 0 ? (
                        <>
                          {userCollections.map((collection, index) => (
                            <CollectionCard
                              key={index}
                              collection={collection}
                              type="user"
                            />
                          ))}
                          <SearchSection type="user" />
                        </>
                      ) : (
                        <div className="rounded-lg border bg-gray-50 py-8 text-center">
                          <FileText className="mx-auto mb-2 h-10 w-10 text-gray-300" />
                          <p className="text-gray-500">
                            No user collections found. Upload some documents to
                            get started!
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </TabsContent>
              </Tabs>
            )}
          </CardContent>
          {selectedCollection && (
            <CardFooter className="border-t py-3">
              <PaginationControls />
            </CardFooter>
          )}
        </Card>
      )}
    </div>
  )
}
