import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from '@/api/client'
import AdminLayout from '@/layouts/AdminLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { title: '登录', public: true },
    },
    {
      path: '/',
      component: AdminLayout,
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('@/views/Dashboard.vue'),
          meta: { title: '概览' },
        },
        {
          path: 'tasks',
          name: 'TaskList',
          component: () => import('@/views/TaskList.vue'),
          meta: { title: '任务列表' },
        },
        {
          path: 'tasks/:id',
          name: 'TaskDetail',
          component: () => import('@/views/TaskDetail.vue'),
          meta: { title: '任务详情' },
          props: true,
        },
        {
          path: 'upload',
          name: 'Upload',
          component: () => import('@/views/Upload.vue'),
          meta: { title: '上传' },
        },
        {
          path: 'process',
          name: 'ProcessDocuments',
          component: () => import('@/views/ProcessDocuments.vue'),
          meta: { title: '处理文档' },
        },
        {
          path: 'download',
          name: 'Download',
          component: () => import('@/views/Download.vue'),
          meta: { title: '下载中心' },
        },
        {
          path: 'templates',
          name: 'Templates',
          component: () => import('@/views/Templates.vue'),
          meta: { title: '模板管理' },
        },
        {
          path: 'evidence',
          name: 'Evidence',
          component: () => import('@/views/EvidencePage.vue'),
          meta: { title: '证据整理' },
        },
        {
          path: 'admin',
          name: 'Admin',
          component: () => import('@/views/Admin.vue'),
          meta: { title: '管理后台', requiresAdmin: true },
        },
        {
          path: 'profile',
          name: 'Profile',
          component: () => import('@/views/Profile.vue'),
          meta: { title: '个人中心' },
        },
      ],
    },
  ],
})

// ─── 路由守卫：认证检查 ───
router.beforeEach((to, _from, next) => {
  const isPublic = to.meta.public === true

  if (isPublic) {
    // 已登录用户访问登录页 → 跳转首页
    if (to.name === 'Login' && isLoggedIn()) {
      next('/dashboard')
      return
    }
    next()
    return
  }

  // 非公开路由：检查是否登录
  if (!isLoggedIn()) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  next()
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'ScanStruct'
  document.title = `${title} — ScanStruct Admin`
})

export default router
