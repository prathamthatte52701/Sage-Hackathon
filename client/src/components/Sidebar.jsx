import React, { useState } from "react";
import {
  LayoutDashboard,
  ShieldAlert,
  Code2,
  FolderGit2,
  MessageSquareCode,
  Network,
  History,
  ChevronLeft,
  ChevronRight,
  Terminal,
  CheckCircle2,
  Lock,
} from "lucide-react";

export default function Sidebar({
  activeTab,
  setActiveTab,
  project,
  hasFindings,
  mobileOpen = false,
  onCloseMobile,
}) {
  const [collapsed, setCollapsed] = useState(false);
  const hasProject = Boolean(project);

  const navItems = [
    {
      id: "overview",
      label: "Overview",
      icon: LayoutDashboard,
      badge: project?.score ? `${Math.round(project.score.overall_score || project.score.health_score || 0)}/100` : null,
      badgeColor: project?.score?.overall_score > 75 ? "text-[#36D399]" : "text-[#F4C95D]",
    },
    {
      id: "findings",
      label: "Findings",
      icon: ShieldAlert,
      badge: project?.findings?.length || null,
      badgeColor: "text-[#FF5D73]",
      disabled: !hasFindings,
    },
    {
      id: "paste_review",
      label: "Paste & Review",
      icon: Code2,
    },
    {
      id: "projects",
      label: "Projects",
      icon: FolderGit2,
    },
    {
      id: "chat",
      label: "Codebase Chat",
      icon: MessageSquareCode,
      disabled: !hasProject,
    },
    {
      id: "architecture",
      label: "Architecture",
      icon: Network,
      disabled: !hasProject,
    },
    {
      id: "history",
      label: "History",
      icon: History,
    },
  ];

  return (
    <>
    {mobileOpen && (
      <button
        type="button"
        aria-label="Close navigation"
        onClick={onCloseMobile}
        className="fixed inset-0 z-40 bg-[#090B10]/70 backdrop-blur-sm lg:hidden"
      />
    )}
    <aside
      className={`fixed lg:sticky top-0 left-0 h-screen bg-[#090B10] border-r border-[#232936] flex flex-col justify-between transition-all duration-200 z-50 lg:z-30 select-none ${
        collapsed ? "lg:w-[72px]" : "lg:w-[220px]"
      } w-[220px] ${
        mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
      }`}
    >
      {/* Top Header Logo */}
      <div>
        <div className="h-16 px-4 border-b border-[#232936] flex items-center justify-between">
          {!collapsed ? (
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF] font-bold">
                <Terminal className="w-4 h-4" />
              </div>
              <div className="flex flex-col">
                <span className="font-semibold text-sm tracking-tight text-[#F4F7FB]">
                  CODE MASTER
                </span>
                <span className="text-[10px] font-mono text-[#7C8CFF] font-medium tracking-wide uppercase">
                  AI Intelligence
                </span>
              </div>
            </div>
          ) : (
            <div className="w-full flex justify-center">
              <div className="w-9 h-9 rounded-lg bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
                <Terminal className="w-5 h-5" />
              </div>
            </div>
          )}
        </div>

        {/* Navigation items */}
        <nav className="p-2 space-y-1 mt-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            const disabled = Boolean(item.disabled);
            return (
              <button
                key={item.id}
                onClick={() => {
                  if (!disabled) setActiveTab(item.id);
                }}
                disabled={disabled}
                title={collapsed || disabled ? disabled ? `${item.label} requires an imported project` : item.label : undefined}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? "bg-[#151922] text-[#F4F7FB] border border-[#232936]"
                    : disabled
                    ? "text-[#4B5565] cursor-not-allowed"
                    : "text-[#9AA4B2] hover:text-[#F4F7FB] hover:bg-[#10131A]"
                }`}
              >
                <Icon
                  className={`w-4 h-4 shrink-0 ${
                    isActive ? "text-[#7C8CFF]" : disabled ? "text-[#343D50]" : "text-[#687386]"
                  }`}
                />
                {!collapsed && (
                  <div className="flex items-center justify-between w-full">
                    <span className="truncate">{item.label}</span>
                    {disabled && <Lock className="w-3 h-3 text-[#4B5565]" />}
                    {item.badge !== null && item.badge !== undefined && (
                      <span
                        className={`text-[10px] font-mono font-semibold px-1.5 py-0.5 rounded bg-[#10131A] border border-[#232936] ${item.badgeColor}`}
                      >
                        {item.badge}
                      </span>
                    )}
                  </div>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Footer System Status & Collapse Toggle */}
      <div className="p-3 border-t border-[#232936] space-y-2">
        {!collapsed && project && (
          <div className="p-2.5 rounded-lg bg-[#10131A] border border-[#232936]">
            <div className="text-[11px] font-mono text-[#687386] truncate">
              Active Repository
            </div>
            <div className="text-xs font-medium text-[#F4F7FB] truncate mt-0.5 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#36D399] shrink-0" />
              <span className="truncate">{project.name || "Imported Repo"}</span>
            </div>
          </div>
        )}

        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full flex items-center justify-center p-2 rounded-lg text-[#687386] hover:text-[#F4F7FB] hover:bg-[#10131A] transition-colors"
          title={collapsed ? "Expand Sidebar" : "Collapse Sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <div className="flex items-center gap-2 text-xs font-medium w-full px-1">
              <ChevronLeft className="w-4 h-4" />
              <span>Collapse Sidebar</span>
            </div>
          )}
        </button>
      </div>
    </aside>
    </>
  );
}
