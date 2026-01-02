function esc(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  })
}

function stripTags(s) {
  return String(s || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()
}

async function loadFeed() {
  const feed = document.getElementById("feed")
  feed.innerHTML = ""

  try {
    const r = await fetch("/api/articles?limit=6")
    const data = await r.json()

    for (const item of (data.items || [])) {
      const title = item.title || "Без названия"
      const link = item.link || "#"
      const author = item.author || (item.author_detail && item.author_detail.name) || ""
      const published = item.published || item.updated || ""
      const summary = stripTags(item.summary || (item.content && item.content[0] && item.content[0].value) || "")

      const el = document.createElement("article")
      el.className = "feed-item article"

      el.innerHTML = `
        <header class="article-header">
          <div class="author">
            <img src="/static/img/avatar.png" alt="">
            <a href="#">${esc(author || "—")}</a>
            <time>${esc(published)}</time>
          </div>
          <h2>
            <a href="${esc(link)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>
          </h2>
        </header>

        <div class="article-preview">
          <p>${esc(summary)}</p>
        </div>
      `

      feed.appendChild(el)
    }

    if (!data.items || data.items.length === 0) {
      feed.innerHTML = `<div class="feed-item">Пусто</div>`
    }
  } catch (e) {
    feed.innerHTML = `<div class="feed-item">Не получилось загрузить RSS</div>`
  }
}

document.addEventListener("DOMContentLoaded", loadFeed)
