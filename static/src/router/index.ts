import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('@/views/Dashboard.vue'),
      meta: { title: '概览' },
    },
    {
      path: '/tasks',
      name: 'TaskList',
      component: () => import('@/views/TaskList.vue'),
      meta: { title: '任务列表' },
    },
    {
      path: '/tasks/:id',
      name: 'TaskDetail',
      component: () => import('@/views/TaskDetail.vue'),
      meta: { title: '任务详情' },
      props: true,
    },
    {
      path: '/upload',
      name: 'Upload',
      component: () => import('@/views/Upload.vue'),
      meta: { title: '上传' },
    },
    {
      path: '/process',
      name: 'ProcessDocuments',
      component: () => import('@/views/ProcessDocuments.vue'),
      meta: { title: '处理文档' },
    },
    {
      path: '/download',
      name: 'Download',
      component: () => import('@/views/Download.vue'),
      meta: { title: '下载中心' },
    },
    {
      path: '/templates',
      name: 'Templates',
      component: () => import('@/views/Templates.vue'),
      meta: { title: '模板管理' },
    },
    {
      path: '/evidence',
      name: 'Evidence',
      component: () => import('@/views/EvidencePage.vue'),
      meta: { title: '证据整理' },
    },
  ],
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'ScanStruct'
  document.title = `${title} — ScanStruct Admin`
})

export default router
