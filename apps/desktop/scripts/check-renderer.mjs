import { chromium } from 'playwright'

const browser = await chromium.launch()
const page = await browser.newPage()
const errors = []

page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`console: ${m.text()}`)
})

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle', timeout: 30000 })
await page.waitForTimeout(3000)

const rootHtml = await page.locator('#root').innerHTML().catch(() => '')
const axewType = await page.evaluate(() => typeof window.axew)

console.log('axew:', axewType)
console.log('root length:', rootHtml.length)
console.log('root preview:', rootHtml.slice(0, 300))
console.log('errors:', errors.length ? errors.join('\n') : '(none)')

await browser.close()
