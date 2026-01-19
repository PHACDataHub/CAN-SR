'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Card, CardHeader, CardContent, CardTitle } from '@/components/ui/card'
import {
  ChevronDown,
  DollarSign,
  Settings,
  User,
  SlidersHorizontal,
  FolderOpen,
} from 'lucide-react'
import type { User as UserType } from '@/lib/auth'

interface SidebarProps {
  sessionCost: number
  onAdvancedSettingsOpen: () => void
  onManageFiles: () => void
  isOpen: boolean
  user: UserType | null
  isUserLoading: boolean
}

export function Sidebar({
  sessionCost,
  onAdvancedSettingsOpen,
  onManageFiles,
  isOpen,
  user,
  isUserLoading,
}: SidebarProps) {
  const [openSections, setOpenSections] = useState({
    files: false,
    advanced: false,
  })

  const toggleSection = (section: string) => {
    setOpenSections((prev) => ({
      ...prev,
      [section]: !prev[section as keyof typeof prev],
    }))
  }

  if (!isOpen) return null

  return (
    <div className="font-smoothing-fix flex h-full w-80 flex-col border-r border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-200 p-5">
        <div className="mb-6 flex items-center">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#26374a]">
            <Settings className="h-4 w-4 text-white" />
          </div>
          <h2 className="ml-3 text-lg font-semibold text-gray-900">Settings</h2>
        </div>

        {/* Fancier Session Cost Tracker */}
        <Card className="border-gray-200 bg-gradient-to-br from-gray-50 to-gray-100 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Session Cost</CardTitle>
            <DollarSign className="h-4 w-4 text-gray-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-gray-900">
              ${sessionCost.toFixed(4)}
            </div>
            <p className="text-xs text-gray-500">CAD</p>
          </CardContent>
        </Card>
      </div>

      {/* Scrollable Settings */}
      <div className="hide-scrollbar flex-1 space-y-4 overflow-y-auto p-4">
        {/* File Management */}
        <Collapsible
          open={openSections.files}
          onOpenChange={() => toggleSection('files')}
        >
          <CollapsibleTrigger className="flex w-full items-center justify-between rounded-lg p-3 text-left hover:bg-gray-50">
            <div className="flex items-center gap-3">
              <FolderOpen className="h-4 w-4 text-gray-600" />
              <div className="min-w-0">
                <div className="truncate font-medium text-gray-900">
                  File Management
                </div>
                <div className="text-xs text-gray-500">
                  Upload and manage your documents
                </div>
              </div>
            </div>
            <ChevronDown
              className={`h-4 w-4 shrink-0 transition-transform ${
                openSections.files ? 'rotate-180' : ''
              }`}
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 space-y-4 px-3">
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <div className="space-y-3">
                {/* File Manager Button */}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onManageFiles}
                  className="w-full hover:border-gray-300 hover:bg-gray-100 hover:text-gray-900"
                >
                  <FolderOpen className="mr-2 h-4 w-4" />
                  Manage Files
                </Button>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {/* Advanced Settings */}
        <Collapsible
          open={openSections.advanced}
          onOpenChange={() => toggleSection('advanced')}
        >
          <CollapsibleTrigger className="flex w-full items-center justify-between rounded-lg p-3 text-left hover:bg-gray-50">
            <div className="flex items-center gap-3">
              <SlidersHorizontal className="h-4 w-4 text-gray-600" />
              <div className="min-w-0">
                <div className="truncate font-medium text-gray-900">
                  Advanced Settings
                </div>
                <div className="text-xs text-gray-500">
                  Retrieval, Database, etc.
                </div>
              </div>
            </div>
            <ChevronDown
              className={`h-4 w-4 shrink-0 transition-transform ${
                openSections.advanced ? 'rotate-180' : ''
              }`}
            />
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 space-y-4 px-3">
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
              <p className="mb-3 text-sm text-gray-700">
                For power users: fine-tune retrieval, generation, and database
                settings.
              </p>
              <Button
                onClick={onAdvancedSettingsOpen}
                className="w-full bg-[#26374a] hover:bg-[#1a2533]"
              >
                Open Advanced Settings
              </Button>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>

      {/* Footer with User Profile */}
      <div className="border-t border-gray-200 p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200">
            <User className="h-4 w-4 text-gray-600" />
          </div>
          <div className="min-w-0">
            {isUserLoading ? (
              <>
                <div className="h-4 w-20 animate-pulse rounded bg-gray-300"></div>
                <div className="mt-1 h-3 w-32 animate-pulse rounded bg-gray-200"></div>
              </>
            ) : user ? (
              <>
                <p className="truncate text-sm font-semibold">
                  {user.full_name}
                </p>
                <p className="truncate text-xs text-gray-500">{user.email}</p>
              </>
            ) : (
              <>
                <p className="truncate text-sm font-semibold">Guest User</p>
                <p className="truncate text-xs text-gray-500">Not logged in</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
