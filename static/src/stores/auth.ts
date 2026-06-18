/**
 * Auth Store — 全局用户信息缓存
 *
 * 解决 P2-U11：消除 AdminLayout/Dashboard/Admin/UsageView/Profile 等多个页面
 * 重复请求 /auth/me 的问题，统一在 store 中缓存。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { get, isLoggedIn, type UserInfo } from '@/api/client'

export const useAuthStore = defineStore('auth', () => {
  const userInfo = ref<UserInfo | null>(null)
  const loading = ref(false)
  let inflight: Promise<UserInfo | null> | null = null

  const isAdmin = computed(() => {
    const role = userInfo.value?.role
    return role === 'tenant_admin' || role === 'super_admin'
  })

  const isSuperAdmin = computed(() => userInfo.value?.role === 'super_admin')

  /** 加载当前用户信息（带去重） */
  async function loadUserInfo(force = false): Promise<UserInfo | null> {
    if (!isLoggedIn()) {
      userInfo.value = null
      return null
    }
    if (!force && userInfo.value) return userInfo.value
    if (inflight) return inflight

    loading.value = true
    inflight = (async () => {
      try {
        const info = await get<UserInfo>('/auth/me')
        userInfo.value = info
        return info
      } catch {
        userInfo.value = null
        return null
      } finally {
        loading.value = false
        inflight = null
      }
    })()
    return inflight
  }

  function clear(): void {
    userInfo.value = null
    inflight = null
  }

  return {
    userInfo,
    loading,
    isAdmin,
    isSuperAdmin,
    loadUserInfo,
    clear,
  }
})
