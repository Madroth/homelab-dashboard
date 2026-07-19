document.addEventListener('DOMContentLoaded', () => {
    const articlesListEl = document.getElementById('articles-list');
    const readerViewEl = document.getElementById('reader-view');
    const searchInput = document.getElementById('search-input');
    const queueListEl = document.getElementById('queue-list');
    
    // Navigation
    const navHome = document.getElementById('nav-home');
    const navIntake = document.getElementById('nav-intake');
    const navMods = document.getElementById('nav-mods');
    const navMedia = document.getElementById('nav-media');
    const navSettings = document.getElementById('nav-settings');
    const navSystem = document.getElementById('nav-system');
    
    const viewHome = document.getElementById('view-home');
    const viewIntake = document.getElementById('view-intake');
    const viewMods = document.getElementById('view-mods');
    const viewMedia = document.getElementById('view-media');
    const viewSettings = document.getElementById('view-settings');
    const viewSystem = document.getElementById('view-system');
    
    const navItems = [navHome, navIntake, navMods, navMedia, navSettings, navSystem];
    const views = [viewHome, viewIntake, viewMods, viewMedia, viewSettings, viewSystem];

    function switchView(viewId) {
        views.forEach(v => {
            if (v) v.style.display = 'none';
        });
        navItems.forEach(n => {
            if (n) {
                n.classList.remove('active');
                n.style.background = 'transparent';
                n.style.color = '#9399b2';
            }
        });

        const v = document.getElementById(`view-${viewId}`);
        const n = document.getElementById(`nav-${viewId}`);
        if (v) v.style.display = viewId === 'intake' ? 'flex' : 'block';
        if (n) {
            n.classList.add('active');
            n.style.background = 'rgba(165,180,252,0.1)';
            n.style.color = '#e4e4f0';
        }
        
        if (viewId === 'intake') applyArticleFilter();
        if (viewId === 'mods') fetchMods();
        if (viewId === 'media') fetchMediaQueue();
    }

    if (navHome) navHome.addEventListener('click', () => switchView('home'));
    if (navIntake) navIntake.addEventListener('click', () => switchView('intake'));
    if (navMods) navMods.addEventListener('click', () => { switchView('mods'); fetchMods(); });
    if (navMedia) navMedia.addEventListener('click', () => { switchView('media'); fetchMediaQueue(); });
    if (navSettings) navSettings.addEventListener('click', () => switchView('settings'));
    if (navSystem) navSystem.addEventListener('click', () => { switchView('system'); loadSystemStatus(); });

    const modsListEl = document.getElementById('mods-list');
    const stagingListEl = document.getElementById('staging-list');
    const navModsBadge = document.getElementById('nav-mods-badge');

    // AI Sidebar
    const aiToggleBtn = document.getElementById('ai-toggle-btn');
    const aiSidebar = document.getElementById('ai-sidebar');
    const aiCloseBtn = document.getElementById('ai-close-btn');
    const aiSendBtn = document.getElementById('ai-send-btn');
    const aiChatInput = document.getElementById('ai-chat-input');
    const aiChatHistory = document.getElementById('ai-chat-history');
    
    let chatHistory = [];

    function toggleAISidebar() {
        if (aiSidebar.style.marginRight === '-320px') {
            aiSidebar.style.marginRight = '0';
        } else {
            aiSidebar.style.marginRight = '-320px';
        }
    }

    if (aiToggleBtn) aiToggleBtn.addEventListener('click', toggleAISidebar);
    if (aiCloseBtn) aiCloseBtn.addEventListener('click', toggleAISidebar);

    function sendAIMessage() {
        const text = aiChatInput.value.trim();
        if (!text) return;
        
        const userMsg = document.createElement('div');
        userMsg.style.cssText = 'display:flex;gap:10px;flex-direction:row-reverse';
        userMsg.innerHTML = `
            <div style="width:24px;height:24px;border-radius:6px;background:rgba(255,255,255,0.1);color:#e4e4f0;display:flex;align-items:center;justify-content:center;flex:none;font-weight:700;font-size:11px">U</div>
            <div style="background:#a5b4fc;padding:10px 12px;border-radius:8px 0 8px 8px;color:#1e1e2e;line-height:1.5">${text.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>
        `;
        aiChatHistory.appendChild(userMsg);
        aiChatInput.value = '';
        aiChatHistory.scrollTop = aiChatHistory.scrollHeight;
        
        const loadingMsg = document.createElement('div');
        loadingMsg.id = 'ai-loading-msg';
        loadingMsg.style.cssText = 'display:flex;gap:10px';
        loadingMsg.innerHTML = `
            <div style="width:24px;height:24px;border-radius:6px;background:rgba(165,180,252,0.15);color:#a5b4fc;display:flex;align-items:center;justify-content:center;flex:none"><i class="fa-solid fa-robot" style="font-size:11px"></i></div>
            <div style="background:#242435;padding:10px 12px;border-radius:0 8px 8px 8px;color:#9399b2;line-height:1.5;display:flex;align-items:center;gap:4px">
              <i class="fa-solid fa-circle fa-beat" style="font-size:4px"></i>
              <i class="fa-solid fa-circle fa-beat" style="font-size:4px;animation-delay:0.1s"></i>
              <i class="fa-solid fa-circle fa-beat" style="font-size:4px;animation-delay:0.2s"></i>
            </div>
        `;
        aiChatHistory.appendChild(loadingMsg);
        aiChatHistory.scrollTop = aiChatHistory.scrollHeight;
        
        chatHistory.push({ role: 'user', text: text });
        
        fetch('/api/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                message: text, 
                history: chatHistory.slice(0, -1),
                model: document.getElementById('ai-model-select').value 
            })
        }).then(res => res.json()).then(data => {
            const loadingNode = document.getElementById('ai-loading-msg');
            if (loadingNode) loadingNode.remove();
            
            chatHistory.push({ role: 'model', text: data.reply || 'No response' });
            
            const botMsg = document.createElement('div');
            botMsg.style.cssText = 'display:flex;gap:10px';
            botMsg.innerHTML = `
                <div style="width:24px;height:24px;border-radius:6px;background:rgba(165,180,252,0.15);color:#a5b4fc;display:flex;align-items:center;justify-content:center;flex:none"><i class="fa-solid fa-robot" style="font-size:11px"></i></div>
                <div style="background:#242435;padding:10px 12px;border-radius:0 8px 8px 8px;color:#e4e4f0;line-height:1.5;overflow-x:hidden" class="markdown-body"></div>
            `;
            const mdContainer = botMsg.querySelector('.markdown-body');
            mdContainer.innerHTML = marked.parse(data.reply || 'No response');
            mdContainer.style.fontSize = '12.5px';
            
            aiChatHistory.appendChild(botMsg);
            aiChatHistory.scrollTop = aiChatHistory.scrollHeight;
        }).catch(err => {
            const loadingNode = document.getElementById('ai-loading-msg');
            if (loadingNode) loadingNode.remove();
            
            const errorMsg = document.createElement('div');
            errorMsg.style.cssText = 'display:flex;gap:10px';
            errorMsg.innerHTML = `
                <div style="width:24px;height:24px;border-radius:6px;background:rgba(243,139,168,0.15);color:#f38ba8;display:flex;align-items:center;justify-content:center;flex:none"><i class="fa-solid fa-triangle-exclamation" style="font-size:11px"></i></div>
                <div style="background:#242435;padding:10px 12px;border-radius:0 8px 8px 8px;color:#f38ba8;line-height:1.5">Sorry, I encountered an error communicating with the backend.</div>
            `;
            aiChatHistory.appendChild(errorMsg);
            aiChatHistory.scrollTop = aiChatHistory.scrollHeight;
        });
    }

    if (aiSendBtn) aiSendBtn.addEventListener('click', sendAIMessage);
    if (aiChatInput) {
        aiChatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendAIMessage();
            }
        });
    }

    let allArticles = [];
    let allMods = {};
    let currentFilter = 'manual'; // keeping it simple
    let currentFolder = 'all';
    let lastFailedCount = 0;

    marked.setOptions({ gfm: true, breaks: true, headerIds: true });

    document.getElementById('home-module-articles').addEventListener('click', () => switchView('intake'));
    document.getElementById('home-module-mods').addEventListener('click', () => switchView('mods'));

    document.querySelectorAll('.folder-item').forEach(folderEl => {
        folderEl.addEventListener('click', () => {
            document.querySelectorAll('.folder-item').forEach(f => {
                f.classList.remove('active');
                f.style.color = '#9399b2';
                f.style.background = 'transparent';
            });
            folderEl.classList.add('active');
            folderEl.style.color = '#e4e4f0';
            folderEl.style.background = 'rgba(165,180,252,0.1)';
            currentFolder = folderEl.dataset.folder;
            queueListEl.style.display = (currentFolder === 'all' || currentFolder === 'errors') ? 'block' : 'none';
            applyArticleFilter();
        });
    });

    function updateFolderCounts() {
        const homelabCount = allArticles.filter(a => a.category === 'Homelab' && !a.is_duplicate).length;
        const newsCount = allArticles.filter(a => a.category === 'News' && !a.is_duplicate).length;
        const errorsCount = allArticles.filter(a => a.is_duplicate).length + lastFailedCount;

        document.getElementById('folder-count-all').innerText = allArticles.length;
        document.getElementById('folder-count-homelab').innerText = homelabCount;
        document.getElementById('folder-count-news').innerText = newsCount;
        document.getElementById('folder-count-errors').innerText = errorsCount;
    }

    async function fetchArticles() {
        try {
            fetchQueue();
            
            let skeletonHtml = '';
            for(let i=0; i<5; i++) {
                skeletonHtml += `<div style="padding:11px 10px;display:flex;flex-direction:column;gap:8px">
                    <div style="height:10px;width:40%;border-radius:4px;background:linear-gradient(90deg,#242435 0%,#2c2c40 50%,#242435 100%);background-size:400px 100%;animation:omegaShimmer 1.4s ease-in-out infinite"></div>
                    <div style="height:13px;width:85%;border-radius:4px;background:linear-gradient(90deg,#242435 0%,#2c2c40 50%,#242435 100%);background-size:400px 100%;animation:omegaShimmer 1.4s ease-in-out infinite"></div>
                </div>`;
            }
            articlesListEl.innerHTML = skeletonHtml;
            
            const response = await fetch('/api/articles');
            if (!response.ok) throw new Error('Network response was not ok');
            
            allArticles = await response.json();
            applyArticleFilter();
            
            // Home modules update
            document.getElementById('home-articles-count').innerText = allArticles.length;
            const homeLatestArt = document.getElementById('home-latest-articles');
            homeLatestArt.innerHTML = '';
            if (allArticles.length === 0) {
                homeLatestArt.innerHTML = `<div style="font-size:12px;color:#6c7086;padding:5px 0;border-top:1px solid rgba(255,255,255,0.05)">No articles yet</div>`;
            } else {
                allArticles.slice(0, 3).forEach(a => {
                    homeLatestArt.innerHTML += `<div style="font-size:12px;color:#c2c6d6;padding:5px 0;border-top:1px solid rgba(255,255,255,0.05);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${a.title}</div>`;
                });
            }
        } catch (error) {
            articlesListEl.innerHTML = `<div style="padding:24px;text-align:center;color:#ef4444">Failed to load articles.</div>`;
        }
    }

    async function fetchQueue() {
        try {
            const response = await fetch('/api/queue');
            if (response.ok) {
                const queue = await response.json();
                renderQueue(queue);
            }
        } catch(e) { }
    }

    function renderQueue(rawQueue) {
        const active = rawQueue ? rawQueue.filter(q => q.status === 'pending' || q.status === 'processing') : [];
        const failed = rawQueue ? rawQueue.filter(q => q.status === 'failed') : [];

        const queueCountEl = document.getElementById('home-queue-count');
        if (queueCountEl) queueCountEl.innerText = active.length;

        const navBadge = document.getElementById('nav-intake-badge');
        if (navBadge) {
            if (failed.length > 0) {
                navBadge.innerText = failed.length;
                navBadge.style.display = 'inline-block';
            } else {
                navBadge.style.display = 'none';
            }
        }

        queueListEl.innerHTML = '';

        if (failed.length > 0) {
            const header = document.createElement('div');
            header.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:10.5px;font-weight:700;letter-spacing:0.4px;color:#f38ba8;margin:2px 4px 6px';
            header.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i>FAILED · CLICK TO RETRY`;
            queueListEl.appendChild(header);

            failed.forEach(item => {
                const el = document.createElement('div');
                el.className = 'btn-icon-hover';
                el.style.cssText = 'padding:10px 10px;border-radius:9px;margin-bottom:6px;background:rgba(243,139,168,0.07);border:1px solid rgba(243,139,168,0.25);cursor:pointer';

                let shortUrl = item.url;
                try { shortUrl = new URL(item.url).hostname; } catch(e){}

                const escapedError = (item.last_error || 'Failed after retries').replace(/"/g, '&quot;');

                el.innerHTML = `
                    <div style="display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:600;margin-bottom:4px;color:#f38ba8">
                      <i class="fa-solid fa-rotate-right" style="font-size:10px"></i>
                      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${shortUrl}</span>
                    </div>
                    <div style="font-size:10px;color:#9399b2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapedError}">${escapedError}</div>
                `;

                el.addEventListener('click', async () => {
                    el.style.opacity = '0.5';
                    el.style.pointerEvents = 'none';
                    await fetch(`/api/queue/${item.id}/retry`, { method: 'POST' });
                    fetchQueue();
                });

                queueListEl.appendChild(el);
            });
        }

        active.forEach(item => {
            const el = document.createElement('div');
            el.style.cssText = 'padding:10px 10px;border-radius:9px;margin-bottom:4px;background:rgba(249,201,124,0.06)';

            let shortUrl = item.url;
            try { shortUrl = new URL(item.url).hostname; } catch(e){}

            const isRetry = item.status === 'pending' && item.retry_count > 0;
            const statusLabel = isRetry ? `RETRY ${item.retry_count}/3` : item.status.toUpperCase();
            const titleAttr = isRetry && item.last_error ? ` title="${item.last_error.replace(/"/g, '&quot;')}"` : '';

            el.innerHTML = `
                <div style="display:flex;align-items:center;gap:8px;font-size:11.5px;font-weight:600;margin-bottom:6px;color:#f9c97c"${titleAttr}>
                  <span style="width:6px;height:6px;border-radius:50%;background:#f9c97c;animation:omegaPulseAmber 2s infinite"></span>
                  <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${shortUrl}</span>
                  <span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 6px;border-radius:9px;background:rgba(249,201,124,0.15);border:1px solid rgba(249,201,124,0.35)">${statusLabel}</span>
                </div>
                <div style="height:3px;border-radius:2px;background:rgba(255,255,255,0.08);overflow:hidden">
                  <div style="height:100%;background:#f9c97c;width:100%;animation:omegaShimmer 1.4s ease-in-out infinite"></div>
                </div>
            `;
            queueListEl.appendChild(el);
        });

        lastFailedCount = failed.length;
        updateFolderCounts();
    }

    function applyArticleFilter() {
        if (viewIntake.style.display === 'none') {
            updateFolderCounts(); // Ensure badges update even if we aren't viewing it
            return;
        }
        const term = searchInput.value.toLowerCase();
        let filtered = allArticles.filter(article =>
            article.title.toLowerCase().includes(term) ||
            (article.raw_content && article.raw_content.includes(term)) ||
            (article.snippet && article.snippet.toLowerCase().includes(term)) ||
            (article.tags && article.tags.some(tag => tag.toLowerCase().includes(term)))
        );

        if (currentFolder === 'homelab') {
            filtered = filtered.filter(a => a.category === 'Homelab' && !a.is_duplicate);
        } else if (currentFolder === 'news') {
            filtered = filtered.filter(a => a.category === 'News' && !a.is_duplicate);
        } else if (currentFolder === 'errors') {
            filtered = filtered.filter(a => a.is_duplicate);
        }

        updateFolderCounts();
        renderArticlesList(filtered);
    }

    function renderArticlesList(articles) {
        if (articles.length === 0) {
            const query = searchInput.value;
            if (query) {
                articlesListEl.innerHTML = `<div style="padding:24px 12px;text-align:center;color:#6c7086;font-size:12.5px">No articles match "${query}"</div>`;
            } else {
                articlesListEl.innerHTML = '<div style="padding:24px 12px;text-align:center;color:#6c7086;font-size:12.5px">No articles found.</div>';
            }
            return;
        }

        articlesListEl.innerHTML = '';
        articles.forEach(article => {
            const card = document.createElement('div');
            card.className = 'article-card-hover';
            card.style.cssText = 'padding:11px 10px;border-radius:9px;cursor:pointer;display:flex;flex-direction:column;gap:5px;transition:background 0.2s';
            card.dataset.id = article.id;
            
            let badgeHtml = '';
            if (article.is_duplicate) {
                badgeHtml = '<span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 7px;border-radius:10px;background:rgba(250,179,135,0.15);color:#fab387;border:1px solid rgba(250,179,135,0.4)">Duplicate</span>';
            } else if (article.auto_generated) {
                badgeHtml = '<span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 7px;border-radius:10px;background:rgba(165,180,252,0.15);color:#a5b4fc;border:1px solid rgba(165,180,252,0.4)">Automated</span>';
            } else {
                badgeHtml = '<span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 7px;border-radius:10px;background:rgba(148,159,178,0.15);color:#b8c0d9;border:1px solid rgba(184,192,217,0.35)">Manual</span>';
            }

            let shortSource = article.source || 'Unknown source';
            try { shortSource = new URL(article.source).hostname; } catch(e){}

            let tagsHtml = '';
            if (article.tags && article.tags.length > 0) {
                const visibleTags = article.tags.slice(0, 3);
                const extraCount = article.tags.length - visibleTags.length;
                tagsHtml = `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">` +
                    visibleTags.map(tag => `<span style="font-size:9.5px;color:#9399b2;background:rgba(255,255,255,0.05);border-radius:8px;padding:1px 7px">${tag}</span>`).join('') +
                    (extraCount > 0 ? `<span style="font-size:9.5px;color:#6c7086;padding:1px 4px">+${extraCount}</span>` : '') +
                    `</div>`;
            }

            card.innerHTML = `
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                  ${badgeHtml}
                  <span style="font-size:10.5px;color:#6c7086;flex:1;text-align:right">${formatDate(article.date)}</span>
                </div>
                <div style="font-size:13.5px;font-weight:600;line-height:1.4;color:#e4e4f0;margin-bottom:4px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;text-overflow:ellipsis" title="${article.title}">${article.title}</div>
                <div style="display:flex;align-items:center;gap:6px;font-size:10.5px;color:#9399b2;margin-bottom:8px">
                  <i class="fa-solid fa-link" style="font-size:9px"></i>
                  <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${shortSource}</span>
                </div>
                <div style="font-size:11.5px;color:#a5b4fc;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;text-overflow:ellipsis;opacity:0.85;margin-bottom:8px">
                  ${article.snippet || 'No summary available.'}
                </div>
                ${tagsHtml}
            `;
            
            card.addEventListener('click', () => {
                document.querySelectorAll('.article-card-hover').forEach(c => c.style.background = 'transparent');
                card.style.background = 'rgba(255,255,255,0.06)';
                loadArticle(article.id);
            });
            
            articlesListEl.appendChild(card);
        });
    }

    async function loadArticle(filename) {
        try {
            readerViewEl.innerHTML = `<div style="height:100%;display:flex;align-items:center;justify-content:center"><i class="fa-solid fa-circle-notch fa-spin" style="font-size:24px;color:#6c7086"></i></div>`;
            const response = await fetch(`/api/articles/${filename}`);
            if (!response.ok) throw new Error('Failed to fetch article content');
            
            const data = await response.json();
            const htmlContent = marked.parse(data.content);
            
            let badgeHtml = '';
            if (data.is_duplicate) {
                badgeHtml = '<span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 7px;border-radius:10px;background:rgba(250,179,135,0.15);color:#fab387;border:1px solid rgba(250,179,135,0.4)">Duplicate</span>';
            } else if (data.auto_generated) {
                badgeHtml = '<span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 7px;border-radius:10px;background:rgba(165,180,252,0.15);color:#a5b4fc;border:1px solid rgba(165,180,252,0.4)">Automated</span>';
            } else {
                badgeHtml = '<span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 7px;border-radius:10px;background:rgba(148,159,178,0.15);color:#b8c0d9;border:1px solid rgba(184,192,217,0.35)">Manual</span>';
            }

            readerViewEl.innerHTML = `
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
                    ${badgeHtml}
                    <span style="font-size:12px;color:#6c7086">${formatDate(data.date)}</span>
                </div>
                <div style="font-size:21px;font-weight:700;margin-bottom:16px;line-height:1.3;color:#e4e4f0">${data.title}</div>
                
                <div class="markdown-body" style="margin-bottom:20px;">${htmlContent}</div>
                
                <div style="display:flex;gap:10px">
                  <div id="btn-delete-article" class="btn-icon-hover" style="padding:8px 14px;border-radius:7px;border:1px solid rgba(243,139,168,0.35);color:#f38ba8;font-size:12px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background 0.2s"><i class="fa-solid fa-trash"></i>Delete</div>
                  <div id="btn-mark-duplicate" class="btn-icon-hover" style="padding:8px 14px;border-radius:7px;border:1px solid rgba(255,255,255,0.12);color:#9399b2;font-size:12px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background 0.2s"><i class="fa-solid fa-copy"></i>Toggle Duplicate</div>
                  <div id="btn-resubmit-article" class="btn-icon-hover" style="padding:8px 14px;border-radius:7px;border:1px solid rgba(165,180,252,0.35);color:#a5b4fc;font-size:12px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background 0.2s"><i class="fa-solid fa-rotate"></i>Resubmit</div>
                </div>
            `;

            document.getElementById('btn-mark-duplicate').addEventListener('click', async () => {
                await fetch(`/api/articles/${filename}/duplicate`, { method: 'POST' });
                fetchArticles().then(() => loadArticle(filename));
            });

            document.getElementById('btn-resubmit-article').addEventListener('click', async (e) => {
                e.currentTarget.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>Resubmitting...';
                const res = await fetch(`/api/articles/${filename}/resubmit`, { method: 'POST' });
                const result = await res.json();
                if (result.success) {
                    e.currentTarget.innerHTML = '<i class="fa-solid fa-check"></i>Queued';
                    fetchQueue();
                } else {
                    alert('Resubmit failed: ' + (result.error || 'Unknown error'));
                    e.currentTarget.innerHTML = '<i class="fa-solid fa-rotate"></i>Resubmit';
                }
            });

            document.getElementById('btn-delete-article').addEventListener('click', async () => {
                if(confirm('Permanently delete this article?')) {
                    await fetch(`/api/articles/${filename}`, { method: 'DELETE' });
                    readerViewEl.innerHTML = `
                        <div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;color:#4c4f61">
                            <i class="fa-solid fa-book-open" style="font-size:28px"></i>
                            <span style="font-size:13.5px;font-weight:500">Select an article to read</span>
                        </div>`;
                    fetchArticles();
                }
            });
            readerViewEl.parentElement.scrollTop = 0;
            
        } catch (error) {
            readerViewEl.innerHTML = `<div style="text-align:center;padding:40px;color:#ef4444;">Error loading article.</div>`;
        }
    }

    const searchClearBtn = document.getElementById('search-clear');
    searchInput.addEventListener('input', (e) => {
        if (e.target.value.length > 0) {
            searchClearBtn.style.display = 'block';
        } else {
            searchClearBtn.style.display = 'none';
        }
        applyArticleFilter();
    });
    searchClearBtn.addEventListener('click', () => {
        searchInput.value = '';
        searchClearBtn.style.display = 'none';
        applyArticleFilter();
    });

    async function fetchMods() {
        try {
            let modSkeletonHtml = '';
            for(let i=0; i<3; i++) {
                modSkeletonHtml += `<div style="height:126px;border-radius:11px;background:linear-gradient(90deg,#242435 0%,#2c2c40 50%,#242435 100%);background-size:400px 100%;animation:omegaShimmer 1.4s ease-in-out infinite"></div>`;
            }
            modsListEl.innerHTML = modSkeletonHtml;
            stagingListEl.innerHTML = modSkeletonHtml;
            
            const [modsRes, stagingRes] = await Promise.all([
                fetch('/api/mods'),
                fetch('/api/mods/staging')
            ]);
            
            if (modsRes.ok) renderModsList(await modsRes.json());
            if (stagingRes.ok) renderStagingList(await stagingRes.json());
            
        } catch (error) {
            console.error('Error fetching mods:', error);
        }
    }

    function renderStagingList(staging) {
        stagingListEl.innerHTML = '';
        
        // Update Home modules
        document.getElementById('home-mods-count').innerText = staging.length;
        const homePendingMods = document.getElementById('home-pending-mods');
        homePendingMods.innerHTML = '';
        if (staging.length === 0) {
            homePendingMods.innerHTML = `<div style="font-size:12px;color:#6c7086;padding:5px 0;border-top:1px solid rgba(255,255,255,0.05)">No pending reviews</div>`;
        } else {
            staging.slice(0, 3).forEach(m => {
                const name = m.meta?.name || m.id;
                homePendingMods.innerHTML += `<div style="font-size:12px;color:#c2c6d6;padding:5px 0;border-top:1px solid rgba(255,255,255,0.05);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${name}</div>`;
            });
        }
        
        if (staging.length > 0) {
            navModsBadge.innerText = staging.length;
            navModsBadge.style.display = 'inline-block';
        } else {
            navModsBadge.style.display = 'none';
        }

        if (staging.length === 0) {
            stagingListEl.innerHTML = '<div style="grid-column: 1/-1; border:1.5px dashed rgba(255,255,255,0.12);border-radius:11px;padding:34px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:#4c4f61;"><i class="fa-solid fa-circle-check" style="font-size:22px"></i><span style="font-size:13px;font-weight:500">No pending reviews</span></div>';
            return;
        }

        staging.forEach(item => {
            const card = document.createElement('div');
            card.style.cssText = 'background:#242435;border:1px solid rgba(255,255,255,0.07);border-radius:11px;padding:16px;display:flex;flex-direction:column;gap:10px;min-width:0';
            
            const modName = item.meta?.name || item.id;
            const submitter = item.sub?.submitted_by || 'Unknown';
            const hash = item.sub?.sha256 ? item.sub.sha256.substring(0, 16) + '...' : 'Unknown';
            const version = item.meta?.version;
            const submittedAt = item.sub?.arrived_at;

            card.innerHTML = `
                <div style="display:flex;align-items:center;gap:9px">
                  <div style="width:30px;height:30px;border-radius:8px;background:rgba(249,201,124,0.14);color:#f9c97c;display:flex;align-items:center;justify-content:center;font-size:13px"><i class="fa-solid fa-cube"></i></div>
                  <div style="flex:1;min-width:0">
                    <div style="display:flex;align-items:center;gap:6px">
                      <span style="font-size:13.5px;font-weight:600;line-height:1.3;color:#e4e4f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${modName}</span>
                      ${version ? `<span style="font-size:9.5px;font-weight:700;color:#9399b2;background:rgba(255,255,255,0.06);border-radius:6px;padding:1px 6px;flex:none">v${version}</span>` : ''}
                    </div>
                    <div style="font-size:11px;color:#9399b2">by ${submitter}${submittedAt ? ' · ' + formatDate(submittedAt) : ''}</div>
                  </div>
                </div>
                <div style="display:flex;align-items:center;gap:6px;font-size:10.5px;color:#6c7086;font-family:'JetBrains Mono',monospace;background:rgba(255,255,255,0.03);border-radius:6px;padding:6px 8px">
                  <i class="fa-solid fa-shield-halved" style="color:#a6e3a1"></i>
                  <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${hash}</span>
                </div>
                <div style="display:flex;gap:8px;margin-top:2px">
                  <div class="review-btn" data-id="${item.id}" style="flex:1;text-align:center;padding:7px 0;border-radius:7px;background:rgba(165,180,252,0.15);color:#a5b4fc;font-size:12px;font-weight:700;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='rgba(165,180,252,0.25)'" onmouseout="this.style.background='rgba(165,180,252,0.15)'"><i class="fa-solid fa-file-lines" style="margin-right:6px"></i>Read Review</div>
                </div>
                <div style="display:flex;gap:8px;margin-top:8px">
                  <div class="approve-btn" data-id="${item.id}" style="flex:1;text-align:center;padding:7px 0;border-radius:7px;background:#a6e3a1;color:#1e1e2e;font-size:12px;font-weight:700;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='#8fd88a'" onmouseout="this.style.background='#a6e3a1'">Approve</div>
                  <div class="reject-btn" data-id="${item.id}" data-name="${modName}" style="flex:1;text-align:center;padding:7px 0;border-radius:7px;border:1px solid rgba(243,139,168,0.35);color:#f38ba8;font-size:12px;font-weight:700;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='rgba(243,139,168,0.1)'" onmouseout="this.style.background='transparent'">Reject</div>
                </div>
            `;
            
            card.querySelector('.review-btn').addEventListener('click', () => {
                const reviewText = item.meta?.ai_review || 'No AI review available.';
                const parsedReview = marked.parse(reviewText);
                const overlay = document.createElement('div');
                overlay.className = 'modal-overlay';
                overlay.innerHTML = `
                    <div class="modal-panel" style="width: 600px; max-height: 80vh; display: flex; flex-direction: column;">
                        <div class="modal-title">AI Review</div>
                        <div class="modal-subtitle">${modName}</div>
                        <div class="markdown-body custom-scroll" style="flex: 1; overflow-y: auto; margin-bottom: 14px; padding-right: 10px;">${parsedReview}</div>
                        <div class="modal-footer">
                            <button class="btn-cancel">Close</button>
                        </div>
                    </div>
                `;
                document.body.appendChild(overlay);
                overlay.querySelector('.btn-cancel').addEventListener('click', () => {
                    document.body.removeChild(overlay);
                });
            });
            
            stagingListEl.appendChild(card);
        });

        document.querySelectorAll('.approve-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const sid = e.currentTarget.dataset.id;
                e.currentTarget.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                e.currentTarget.disabled = true;
                
                const res = await fetch(`/api/mods/approve/${sid}`, { method: 'POST' });
                const result = await res.json();
                if (result.success) {
                    fetchMods();
                } else {
                    alert('Deploy failed: ' + (result.error || 'Unknown error'));
                    fetchMods();
                }
            });
        });

        document.querySelectorAll('.reject-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const sid = e.currentTarget.dataset.id;
                const name = e.currentTarget.dataset.name;
                
                const overlay = document.createElement('div');
                overlay.className = 'modal-overlay';
                overlay.innerHTML = `
                    <div class="modal-panel">
                        <div class="modal-title">Reject mod</div>
                        <div class="modal-subtitle">${name} — this moves the submission to the review folder.</div>
                        <textarea class="modal-textarea" placeholder="Reason for rejection..."></textarea>
                        <div class="modal-footer">
                            <button class="btn-cancel">Cancel</button>
                            <button class="btn-reject-confirm">Confirm Reject</button>
                        </div>
                    </div>
                `;
                document.body.appendChild(overlay);
                
                overlay.querySelector('.btn-cancel').addEventListener('click', () => {
                    document.body.removeChild(overlay);
                });
                
                overlay.querySelector('.btn-reject-confirm').addEventListener('click', async (e2) => {
                    const reason = overlay.querySelector('.modal-textarea').value;
                    e2.currentTarget.innerHTML = 'Rejecting...';
                    e2.currentTarget.disabled = true;
                    
                    const res = await fetch(`/api/mods/reject/${sid}`, { 
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ reason: reason || 'rejected via dashboard' })
                    });
                    const result = await res.json();
                    document.body.removeChild(overlay);
                    if (result.success) {
                        fetchMods();
                    } else {
                        alert('Rejection failed: ' + result.error);
                    }
                });
            });
        });
    }

    function renderModsList(mods) {
        modsListEl.innerHTML = '';
        const modNames = Object.keys(mods);
        
        if (modNames.length === 0) {
            modsListEl.innerHTML = '<div style="grid-column: 1/-1;color:#6c7086;font-size:12.5px">No mods found in registry.</div>';
            return;
        }

        modNames.forEach(modName => {
            const mod = mods[modName];
            const history = mod.history || [];
            const lastUpdate = history.length > 0 ? history[history.length - 1].submitted_at : '';
            const deployedBy = history.length > 0 && history[history.length - 1].decided_by ? history[history.length - 1].decided_by : 'admin';
            const version = mod.version;

            const card = document.createElement('div');
            card.style.cssText = 'background:#242435;border:1px solid rgba(255,255,255,0.05);border-radius:11px;padding:16px;display:flex;flex-direction:column;gap:8px;opacity:0.85;min-width:0';
            card.innerHTML = `
                <div style="display:flex;align-items:center;gap:9px">
                  <div style="width:28px;height:28px;border-radius:7px;background:rgba(166,227,161,0.12);color:#a6e3a1;display:flex;align-items:center;justify-content:center;font-size:12px"><i class="fa-solid fa-check"></i></div>
                  <div style="flex:1;min-width:0">
                    <div style="display:flex;align-items:center;gap:6px">
                      <span style="font-size:13px;font-weight:600;line-height:1.3;color:#e4e4f0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${modName}</span>
                      ${version ? `<span style="font-size:9.5px;font-weight:700;color:#9399b2;background:rgba(255,255,255,0.06);border-radius:6px;padding:1px 6px;flex:none">v${version}</span>` : ''}
                    </div>
                    <div style="font-size:10.5px;color:#9399b2">by ${mod.submitted_by || 'Unknown'}${mod.submitted_at ? ' · submitted ' + formatDate(mod.submitted_at) : ''}</div>
                  </div>
                </div>
                <div style="font-size:11px;color:#6c7086">Approved ${formatDate(lastUpdate)} · deployed by ${deployedBy}</div>
            `;
            modsListEl.appendChild(card);
        });
    }

    function formatDate(dateStr) {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return dateStr;
            return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date);
        } catch(e) {
            return dateStr;
        }
    }

    async function fetchMinecraftStatus() {
        try {
            const res = await fetch('/api/minecraft');
            const data = await res.json();
            
            const statusBar = document.getElementById('mc-status-bar');
            const playersBar = document.getElementById('mc-players-bar');
            const playersCard = document.getElementById('mc-players-card');
            const versionCard = document.getElementById('mc-version-card');
            
            if (data.online) {
                if(statusBar) { statusBar.innerText = 'Online'; statusBar.style.color = '#a6e3a1'; }
                if(playersBar) playersBar.innerText = `${data.players}/${data.max_players}`;
                if(playersCard) playersCard.innerText = `${data.players} / ${data.max_players}`;
                if(versionCard) versionCard.innerText = data.version;
            } else {
                if(statusBar) { statusBar.innerText = 'Offline'; statusBar.style.color = '#f38ba8'; }
                if(playersBar) playersBar.innerText = '0/0';
                if(playersCard) playersCard.innerText = '0 / 0';
                if(versionCard) versionCard.innerText = 'Server offline';
            }
        } catch(e) { }
    }

    // Settings
    function loadSettings() {
        fetch('/api/settings').then(res => res.json()).then(data => {
            if (data.geminiApiKey) document.getElementById('setting-gemini-key').value = data.geminiApiKey;
            if (data.anthropicApiKey) document.getElementById('setting-anthropic-key').value = data.anthropicApiKey;
            if (data.ollamaHost) document.getElementById('setting-ollama-host').value = data.ollamaHost;
        });
    }
    
    document.getElementById('settings-save-btn')?.addEventListener('click', () => {
        const data = {
            geminiApiKey: document.getElementById('setting-gemini-key').value,
            anthropicApiKey: document.getElementById('setting-anthropic-key').value,
            ollamaHost: document.getElementById('setting-ollama-host').value
        };
        fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }).then(res => res.json()).then(res => {
            if (res.success) {
                const btn = document.getElementById('settings-save-btn');
                const origText = btn.innerText;
                btn.innerText = 'Saved!';
                setTimeout(() => { btn.innerText = origText; }, 2000);
            }
        });
    });

    const mediaQueueListEl = document.getElementById('media-queue-list');
    const navMediaBadge = document.getElementById('nav-media-badge');

    async function fetchMediaQueue() {
        try {
            const res = await fetch('/api/media/queue');
            if (res.ok) {
                const queue = await res.json();
                renderMediaQueue(queue);
            }
        } catch(e) { console.error('Media fetch error', e); }
    }

    function renderMediaQueue(queue) {
        if (!mediaQueueListEl) return;
        mediaQueueListEl.innerHTML = '';
        
        if (queue.length > 0) {
            const pendingCount = queue.filter(q => q.status === 'pending').length;
            if(navMediaBadge) {
                if (pendingCount > 0) {
                    navMediaBadge.innerText = pendingCount;
                    navMediaBadge.style.display = 'inline-block';
                } else {
                    navMediaBadge.style.display = 'none';
                }
            }
        } else {
            if(navMediaBadge) navMediaBadge.style.display = 'none';
            mediaQueueListEl.innerHTML = '<div style="color:#6c7086;font-size:12.5px;padding:20px;text-align:center;border:1.5px dashed rgba(255,255,255,0.12);border-radius:11px">Queue is empty. Waiting for media...</div>';
            return;
        }

        queue.forEach(item => {
            const card = document.createElement('div');
            
            if (item.status === 'approved') {
                card.className = 'btn-icon-hover';
                card.style.cssText = 'background:rgba(166,227,161,0.05);border:1px solid rgba(166,227,161,0.2);border-radius:9px;padding:12px;display:flex;align-items:center;gap:10px;cursor:pointer;margin-bottom:8px;transition:background 0.2s';
                
                card.innerHTML = `
                    <div style="width:28px;height:28px;border-radius:7px;background:rgba(166,227,161,0.15);color:#a6e3a1;display:flex;align-items:center;justify-content:center;font-size:12px"><i class="fa-solid fa-check-double"></i></div>
                    <div style="flex:1;min-width:0">
                        <div style="font-size:12.5px;font-weight:600;color:#e4e4f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Auto-sorted: ${item.proposed_title}</div>
                        <div style="font-size:10.5px;color:#9399b2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"><i class="fa-solid fa-folder-tree" style="margin-right:4px"></i>${item.proposed_path}</div>
                    </div>
                    <div style="font-size:10.5px;color:#6c7086">${formatDate(item.created_at)}</div>
                `;
                
                card.addEventListener('click', () => {
                    const escapeHTML = (str) => String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
                    const logic = escapeHTML(item.metadata?.sort_logic || 'No logic recorded.');
                    const shortDesc = escapeHTML(item.metadata?.short_description || 'No short description available.');
                    const longDesc = escapeHTML(item.metadata?.long_description || 'No long description available.');
                    const franchise = escapeHTML(item.metadata?.franchise || 'None');
                    const origFileEsc = escapeHTML(item.original_filename);
                    const propPathEsc = escapeHTML(item.proposed_path);
                    const titleEsc = escapeHTML(item.proposed_title);
                    
                    const overlay = document.createElement('div');
                    overlay.className = 'modal-overlay';
                    overlay.innerHTML = `
                        <div class="modal-panel" style="width: 550px;">
                            <div class="modal-title">Media Details</div>
                            <div class="modal-subtitle">${titleEsc}</div>
                            
                            <div style="margin: 14px 0; display:flex; flex-direction:column; gap:12px; font-size:12.5px; color:#c2c6d6; line-height:1.5; max-height:60vh; overflow-y:auto;" class="custom-scroll">
                                <div>
                                    <strong style="color:#a5b4fc">Category:</strong>
                                    <select id="reclassify-dropdown" style="margin-left:8px; background:#191925; border:1px solid rgba(255,255,255,0.1); color:#e4e4f0; border-radius:4px; padding:2px 6px;">
                                        <option value="movie" ${item.media_type === 'movie' ? 'selected' : ''}>Movie</option>
                                        <option value="tv_show" ${item.media_type === 'tv_show' ? 'selected' : ''}>TV Show</option>
                                        <option value="ebook" ${item.media_type === 'ebook' ? 'selected' : ''}>Ebook</option>
                                        <option value="audiobook" ${item.media_type === 'audiobook' ? 'selected' : ''}>Audiobook</option>
                                        <option value="comic" ${item.media_type === 'comic' ? 'selected' : ''}>Comic</option>
                                    </select>
                                </div>
                                
                                <div style="background:#191925; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:12px;">
                                    <strong style="color:#a5b4fc">Original File:</strong><br>${origFileEsc}
                                    <div style="margin-top:6px; color:#f38ba8; display:${item.original_filename === item.proposed_path ? 'none' : 'block'}">
                                        <strong style="color:#f38ba8">Target Path:</strong><br>${propPathEsc}
                                    </div>
                                </div>
                                <div style="background:#191925; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:12px;">
                                    <strong style="color:#a5b4fc">Series/Grouping:</strong><br>${franchise}
                                </div>
                                <div style="background:#191925; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:12px;">
                                    <strong style="color:#a5b4fc">Short Description:</strong><br>${shortDesc}
                                </div>
                                <div style="background:#191925; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:12px;">
                                    <strong style="color:#a5b4fc">Long Description:</strong><br>${longDesc}
                                </div>
                                <div style="background:#191925; border:1px solid rgba(255,255,255,0.06); border-radius:8px; padding:12px;">
                                    <strong style="color:#a5b4fc">Sorting Logic:</strong><br>${logic}
                                </div>
                            </div>
                            
                            <div class="modal-footer" style="display:flex; gap:10px; justify-content:space-between; width:100%">
                                <div style="display:flex; gap:8px;">
                                    <button class="btn-edit" style="background:rgba(165,180,252,0.15); color:#a5b4fc; border:none; padding:8px 16px; border-radius:6px; font-weight:600; cursor:pointer; display:${item.status === 'approved' ? 'none' : 'block'}">Edit Title</button>
                                    <button class="btn-reject" style="background:rgba(243,139,168,0.15); color:#f38ba8; border:1px solid rgba(243,139,168,0.3); padding:8px 16px; border-radius:6px; font-weight:600; cursor:pointer;">Reject/Delete</button>
                                </div>
                                <button class="btn-cancel">Close</button>
                            </div>
                        </div>
                    `;
                    document.body.appendChild(overlay);
                    
                    overlay.querySelector('.btn-cancel').addEventListener('click', () => document.body.removeChild(overlay));
                    
                    overlay.querySelector('.btn-edit').addEventListener('click', async () => {
                        const newTitle = prompt("Edit Title:", item.proposed_title);
                        if (newTitle && newTitle !== item.proposed_title) {
                            const res = await fetch(`/api/media/edit/${item.id}`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ proposed_title: newTitle })
                            });
                            const result = await res.json();
                            if (res.ok && result.success !== false) {
                                document.body.removeChild(overlay);
                                fetchMediaQueue();
                            } else {
                                alert("Failed to edit title: " + (result.error || "Unknown error"));
                            }
                        }
                    });
                    
                    overlay.querySelector('.btn-reject').addEventListener('click', async () => {
                        if (confirm("Are you sure you want to delete this media item? It will be removed from your library.")) {
                            const res = await fetch(`/api/media/reject/${item.id}`, { method: 'POST' });
                            const result = await res.json();
                            if (res.ok && result.success !== false) {
                                document.body.removeChild(overlay);
                                fetchMediaQueue();
                            } else {
                                alert("Failed to reject/delete: " + (result.error || "Unknown error"));
                            }
                        }
                    });
                    
                    overlay.querySelector('#reclassify-dropdown').addEventListener('change', async (e) => {
                        const newType = e.target.value;
                        e.target.disabled = true;
                        const originalText = overlay.querySelector('.modal-title').innerText;
                        overlay.querySelector('.modal-title').innerText = "Reclassifying... Please wait";
                        
                        try {
                            const res = await fetch(`/api/media/reclassify/${item.id}`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ media_type: newType })
                            });
                            const result = await res.json();
                            if (result.success) {
                                document.body.removeChild(overlay);
                                fetchMediaQueue();
                            } else {
                                alert("Failed to reclassify: " + result.error);
                                overlay.querySelector('.modal-title').innerText = originalText;
                                e.target.disabled = false;
                            }
                        } catch (err) {
                            alert("Error during reclassification.");
                            overlay.querySelector('.modal-title').innerText = originalText;
                            e.target.disabled = false;
                        }
                    });
                });
                
            } else {
                card.style.cssText = 'background:#242435;border:1px solid rgba(255,255,255,0.07);border-radius:11px;padding:16px;display:flex;flex-direction:column;gap:10px;margin-bottom:8px';
                
                const flagHtml = item.needs_intervention ? '<span style="font-size:9.5px;font-weight:700;letter-spacing:0.3px;padding:2px 7px;border-radius:10px;background:rgba(243,139,168,0.15);color:#f38ba8;border:1px solid rgba(243,139,168,0.4);margin-left:8px">NEEDS REVIEW</span>' : '';
                
                const metaInfo = item.metadata ? (item.metadata.year ? `(${item.metadata.year})` : '') : '';
                
                card.innerHTML = `
                    <div style="display:flex;justify-content:space-between;align-items:flex-start">
                        <div>
                            <div style="font-size:11px;color:#9399b2;margin-bottom:4px">Original: ${item.original_filename}</div>
                            <div style="font-size:15px;font-weight:600;color:#e4e4f0">${item.proposed_title} ${metaInfo} ${flagHtml}</div>
                            <div style="font-size:11px;color:#a5b4fc;margin-top:4px"><i class="fa-solid fa-folder-tree" style="margin-right:4px"></i>${item.proposed_path}</div>
                        </div>
                    </div>
                    <div style="display:flex;gap:8px;margin-top:8px">
                      <div class="media-approve-btn" data-id="${item.id}" style="flex:1;text-align:center;padding:7px 0;border-radius:7px;background:#a6e3a1;color:#1e1e2e;font-size:12px;font-weight:700;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='#8fd88a'" onmouseout="this.style.background='#a6e3a1'">Approve</div>
                      <div class="media-edit-btn" data-id="${item.id}" data-title="${item.proposed_title.replace(/"/g, '&quot;')}" style="flex:1;text-align:center;padding:7px 0;border-radius:7px;background:rgba(165,180,252,0.15);color:#a5b4fc;font-size:12px;font-weight:700;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='rgba(165,180,252,0.25)'" onmouseout="this.style.background='rgba(165,180,252,0.15)'">Edit Title</div>
                      <div class="media-reject-btn" data-id="${item.id}" style="flex:1;text-align:center;padding:7px 0;border-radius:7px;border:1px solid rgba(243,139,168,0.35);color:#f38ba8;font-size:12px;font-weight:700;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background='rgba(243,139,168,0.1)'" onmouseout="this.style.background='transparent'">Reject</div>
                    </div>
                `;
                
                card.querySelector('.media-approve-btn').addEventListener('click', async (e) => {
                    e.currentTarget.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                    await fetch(`/api/media/approve/${item.id}`, { method: 'POST' });
                    fetchMediaQueue();
                });
                
                card.querySelector('.media-reject-btn').addEventListener('click', async (e) => {
                    if(confirm("Reject this media item?")) {
                        await fetch(`/api/media/reject/${item.id}`, { method: 'POST' });
                        fetchMediaQueue();
                    }
                });
                
                card.querySelector('.media-edit-btn').addEventListener('click', async (e) => {
                    const newTitle = prompt("Edit Title:", e.currentTarget.dataset.title);
                    if (newTitle && newTitle !== e.currentTarget.dataset.title) {
                        await fetch(`/api/media/edit/${item.id}`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ proposed_title: newTitle })
                        });
                        fetchMediaQueue();
                    }
                });
            }
            mediaQueueListEl.appendChild(card);
        });
    }

    // Initial load
    switchView('home');
    fetchArticles();
    fetchMods();
    fetchMinecraftStatus();
    loadSettings();
    
    // Refresh Minecraft status every 30 seconds
    setInterval(fetchMinecraftStatus, 30000);
    setInterval(fetchMods, 5000);
    setInterval(fetchMediaQueue, 5000);
    setInterval(() => {
        if (document.getElementById('view-system').style.display !== 'none') {
            loadSystemStatus();
        }
    }, 5000);
    
    function loadSystemStatus() {
        fetch('/api/system/status')
            .then(r => r.json())
            .then(data => {
                // Defcon
                const defconEl = document.getElementById('system-defcon');
                if (data.defcon && data.defcon.length > 0) {
                    defconEl.style.display = 'block';
                    defconEl.innerHTML = data.defcon.map(m => `<div><i class="fa-solid fa-triangle-exclamation"></i> ${m}</div>`).join('');
                } else {
                    defconEl.style.display = 'none';
                    defconEl.innerHTML = '';
                }
                
                // Disk
                const diskEl = document.getElementById('system-disk-usage');
                const diskSubEl = document.getElementById('system-disk-sub');
                if (data.disk && data.disk.total) {
                    const totalGb = (data.disk.total / 1073741824).toFixed(1);
                    const freeGb = (data.disk.free / 1073741824).toFixed(1);
                    diskEl.innerText = `${freeGb} GB Free`;
                    diskSubEl.innerText = `Out of ${totalGb} GB Total`;
                    
                    if (data.disk.free_pct < 10) diskEl.style.color = '#f38ba8';
                    else diskEl.style.color = '#e4e4f0';
                }
                
                // Plex Mem
                if (data.memory && data.memory.plex) {
                    document.getElementById('system-plex-mem').innerText = data.memory.plex;
                }
                
                // Daemon
                const daemonEl = document.getElementById('system-daemon-status');
                if (data.daemon_active) {
                    daemonEl.innerText = 'Active (Running)';
                    daemonEl.style.color = '#a6e3a1';
                } else {
                    daemonEl.innerText = 'Failed / Stopped';
                    daemonEl.style.color = '#f38ba8';
                }
                
                // Containers Grid
                const gridEl = document.getElementById('system-containers-grid');
                gridEl.innerHTML = '';
                if (data.containers) {
                    data.containers.forEach(c => {
                        let statusColor = '#a6e3a1';
                        let icon = 'fa-box';
                        if (c.Status.includes('Exited') || c.Status.includes('unhealthy')) {
                            statusColor = '#f38ba8';
                        } else if (c.Status.includes('health: starting') || c.Status.includes('Waiting')) {
                            statusColor = '#f9c97c';
                        }
                        
                        gridEl.innerHTML += `
                            <div style="background:#242435;border:1px solid rgba(255,255,255,0.06);border-radius:9px;padding:12px;display:flex;flex-direction:column;gap:6px">
                                <div style="display:flex;align-items:center;gap:8px;font-weight:600;font-size:12.5px;color:#e4e4f0">
                                    <i class="fa-solid ${icon}" style="color:${statusColor}"></i> ${c.Names}
                                </div>
                                <div style="font-size:10.5px;color:#9399b2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${c.Status}">
                                    ${c.Status}
                                </div>
                            </div>
                        `;
                    });
                }
            })
            .catch(err => console.error(err));
    }
});
