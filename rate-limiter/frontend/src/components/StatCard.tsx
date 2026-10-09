import React from 'react'

interface StatCardProps {
  icon: string
  label: string
  value: string | number
  sub?: string
  accentColor: string
  iconBg: string
}

const StatCard: React.FC<StatCardProps> = ({ icon, label, value, sub, accentColor, iconBg }) => {
  return (
    <div
      className="stat-card"
      style={{ '--card-accent': accentColor, '--card-icon-bg': iconBg } as React.CSSProperties}
    >
      <div className="stat-card-icon">{icon}</div>
      <div className="stat-card-label">{label}</div>
      <div className="stat-card-value animate-number">{value}</div>
      {sub && <div className="stat-card-sub">{sub}</div>}
    </div>
  )
}

export default StatCard
