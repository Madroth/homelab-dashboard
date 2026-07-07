document.addEventListener('DOMContentLoaded', () => {
    const articlesListEl = document.getElementById('articles-list');
    const readerViewEl = document.getElementById('reader-view');
    const refreshBtn = document.getElementById('refresh-btn');
    const searchInput = document.getElementById('search-input');
    const queueListEl = document.getElementById('queue-list');
    const queueSectionEl = document.getElementById('queue-section');
    
    // Mod Pipeline Elements
    const navIntake = document.getElementById('nav-intake');
    const navAutoResearch = document.getElementById('nav-auto-research');
    const navMods = document.getElementById('nav-mods');
    const viewIntake = document.getElementById('view-intake');
    const viewMods = document.getElementById('view-mods');
    const modsListEl = document.getElementById('mods-list');
    const stagingListEl = document.getElementById('staging-list');
    const refreshModsBtn = document.getElementById('refresh-mods-btn');

    let allArticles = [];
    let allMods = {};
    let currentFilter = 'manual'; // 'manual' or 'auto'

    // Configure marked to use GitHub flavored markdown
    marked.setOptions({
        gfm: true,
        breaks: true,
        headerIds: true
    });

    // Fetch articles list
    async function fetchArticles() {
        try {
            fetchQueue(); // also fetch queue
            
            articlesListEl.innerHTML = '<div class="loading-state"><div class="spinner"></div><p>Loading articles...</p></div>';
            
            const response = await fetch('/api/articles');
            if (!response.ok) throw new Error('Network response was not ok');
            
            allArticles = await response.json();
            applyArticleFilter();
            
            // auto selection handled in applyArticleFilter
        } catch (error) {
            articlesListEl.innerHTML = `<div class="loading-state" style="color: #ef4444;"><i class="fa-solid fa-circle-exclamation" style="font-size: 24px; margin-bottom: 12px;"></i><p>Failed to load articles.</p></div>`;
            console.error('Error fetching articles:', error);
        }
    }

    async function fetchQueue() {
        try {
            const response = await fetch('/api/queue');
            if (response.ok) {
                const queue = await response.json();
                renderQueue(queue);
            }
        } catch(e) {
            console.error('Error fetching queue:', e);
        }
    }

    function renderQueue(queue) {
        if (!queue || queue.length === 0) {
            queueSectionEl.style.display = 'none';
            return;
        }
        
        queueSectionEl.style.display = 'block';
        queueListEl.innerHTML = '';
        
        queue.forEach(item => {
            const el = document.createElement('div');
            el.style.fontSize = '12px';
            el.style.display = 'flex';
            el.style.justifyContent = 'space-between';
            el.style.alignItems = 'center';
            el.style.padding = '6px 0';
            el.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
            
            let statusColor = '#94a3b8';
            let icon = 'fa-clock';
            if (item.status === 'processing') { statusColor = '#f59e0b'; icon = 'fa-gear fa-spin'; }
            if (item.status === 'done') { statusColor = '#10b981'; icon = 'fa-check'; }
            if (item.status === 'failed') { statusColor = '#ef4444'; icon = 'fa-xmark'; }
            
            // extract domain/title roughly
            let shortUrl = item.url;
            try { shortUrl = new URL(item.url).hostname; } catch(e){}
            
            el.innerHTML = `
                <div style="display: flex; align-items: center; gap: 8px; overflow: hidden;">
                    <i class="fa-solid ${icon}" style="color: ${statusColor}; width: 14px; text-align: center;"></i>
                    <span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #e2e8f0;" title="${item.url}">${shortUrl}</span>
                </div>
                <span style="font-weight: 600; font-size: 10px; text-transform: uppercase; color: ${statusColor};">${item.status}</span>
            `;
            queueListEl.appendChild(el);
        });
    }

    function applyArticleFilter() {
        const filtered = allArticles.filter(article => {
            if (currentFilter === 'manual') return !article.auto_generated;
            if (currentFilter === 'auto') return article.auto_generated;
            return true;
        });
        
        // Also apply search filter if present
        const term = searchInput.value.toLowerCase();
        const finalFiltered = filtered.filter(article => 
            article.title.toLowerCase().includes(term) || 
            (article.raw_content && article.raw_content.includes(term))
        );
        
        renderArticlesList(finalFiltered);
        
        if (finalFiltered.length > 0) {
            loadArticle(finalFiltered[0].id);
        } else {
            readerViewEl.innerHTML = '<div class="empty-state"><i class="fa-solid fa-file-lines empty-icon"></i><h3>Select an article to read</h3><p>Summaries and homelab ideation will appear here.</p></div>';
        }
    }

    // Render the list of articles in the feed
    function renderArticlesList(articles) {
        if (articles.length === 0) {
            articlesListEl.innerHTML = '<div class="loading-state"><p>No articles found.</p></div>';
            return;
        }

        articlesListEl.innerHTML = '';
        articles.forEach(article => {
            const card = document.createElement('div');
            card.className = 'article-card';
            card.dataset.id = article.id;
            
            card.innerHTML = `
                <div class="article-title" style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <span>${article.title}</span>
                    ${article.is_duplicate ? '<span style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; text-transform: uppercase; border: 1px solid rgba(245, 158, 11, 0.5); white-space: nowrap; margin-left: 8px;">Duplicate</span>' : ''}
                </div>
                <div class="article-meta">
                    <span>${formatDate(article.date) || 'Unknown date'}</span>
                </div>
                <div class="article-snippet">${article.snippet}</div>
            `;
            
            card.addEventListener('click', () => {
                document.querySelectorAll('.article-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                loadArticle(article.id);
            });
            
            articlesListEl.appendChild(card);
        });
    }

    // Load a specific article content
    async function loadArticle(filename) {
        try {
            readerViewEl.classList.remove('empty-state');
            readerViewEl.innerHTML = '<div class="loading-state"><div class="spinner"></div></div>';
            
            // Highlight active card
            document.querySelectorAll('.article-card').forEach(c => {
                if(c.dataset.id === filename) c.classList.add('active');
                else c.classList.remove('active');
            });

            const response = await fetch(`/api/articles/${filename}`);
            if (!response.ok) throw new Error('Failed to fetch article content');
            
            const data = await response.json();
            
            // Render markdown to HTML
            const htmlContent = marked.parse(data.content);
            readerViewEl.innerHTML = `
                <div class="article-actions" style="display: flex; gap: 8px; margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <button id="btn-mark-duplicate" style="background: rgba(245, 158, 11, 0.2); border: 1px solid #f59e0b; color: #f59e0b; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; transition: all 0.2s;"><i class="fa-solid fa-copy" style="margin-right: 4px;"></i> Mark Duplicate</button>
                    <button id="btn-delete-article" style="background: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; color: #ef4444; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; transition: all 0.2s;"><i class="fa-solid fa-trash" style="margin-right: 4px;"></i> Delete</button>
                </div>
                <div class="markdown-body">${htmlContent}</div>
            `;
            
            document.getElementById('btn-mark-duplicate').addEventListener('click', async () => {
                if(confirm('Mark this article as a duplicate? It will be visually marked in the feed and block future submissions.')) {
                    document.getElementById('btn-mark-duplicate').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Working...';
                    await fetch(`/api/articles/${filename}/duplicate`, { method: 'POST' });
                    fetchArticles().then(() => loadArticle(filename));
                }
            });

            document.getElementById('btn-delete-article').addEventListener('click', async () => {
                if(confirm('Permanently delete this article?')) {
                    document.getElementById('btn-delete-article').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Working...';
                    await fetch(`/api/articles/${filename}`, { method: 'DELETE' });
                    readerViewEl.innerHTML = '<div class="empty-state"><i class="fa-solid fa-trash" style="font-size: 32px; color: #ef4444; margin-bottom: 16px;"></i><p>Article deleted.</p></div>';
                    fetchArticles();
                }
            });
            
            // Scroll to top
            readerViewEl.parentElement.scrollTop = 0;
            
        } catch (error) {
            readerViewEl.innerHTML = `<div class="empty-state" style="color: #ef4444;"><i class="fa-solid fa-triangle-exclamation empty-icon"></i><h3>Error loading article</h3><p>${error.message}</p></div>`;
        }
    }

    // Search filtering
    searchInput.addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        
        // If we are on the Mod Pipeline view, search mods instead
        if (viewMods.style.display === 'flex') {
            const modNames = Object.keys(allMods);
            const filteredMods = {};
            modNames.forEach(name => {
                if (name.toLowerCase().includes(term) || (allMods[name].current_filename && allMods[name].current_filename.toLowerCase().includes(term))) {
                    filteredMods[name] = allMods[name];
                }
            });
            renderModsList(filteredMods);
            return;
        }

        // Article search
        applyArticleFilter();
    });

    refreshBtn.addEventListener('click', () => {
        const icon = refreshBtn.querySelector('i');
        icon.style.animation = 'spin 1s linear infinite';
        fetchArticles().then(() => {
            setTimeout(() => icon.style.animation = '', 500);
        });
    });

    // Navigation Switching
    navIntake.addEventListener('click', (e) => {
        e.preventDefault();
        currentFilter = 'manual';
        navIntake.classList.add('active');
        if (navAutoResearch) navAutoResearch.classList.remove('active');
        navMods.classList.remove('active');
        viewIntake.style.display = 'flex';
        viewMods.style.display = 'none';
        applyArticleFilter();
    });

    if (navAutoResearch) {
        navAutoResearch.addEventListener('click', (e) => {
            e.preventDefault();
            currentFilter = 'auto';
            navAutoResearch.classList.add('active');
            navIntake.classList.remove('active');
            navMods.classList.remove('active');
            viewIntake.style.display = 'flex';
            viewMods.style.display = 'none';
            applyArticleFilter();
        });
    }

    navMods.addEventListener('click', (e) => {
        e.preventDefault();
        navMods.classList.add('active');
        navIntake.classList.remove('active');
        if (navAutoResearch) navAutoResearch.classList.remove('active');
        viewMods.style.display = 'flex';
        viewIntake.style.display = 'none';
        fetchMods();
    });

    // Fetch and render mods
    async function fetchMods() {
        try {
            modsListEl.innerHTML = '<div class="loading-state" style="grid-column: 1/-1"><div class="spinner"></div><p>Loading mods...</p></div>';
            stagingListEl.innerHTML = '<div class="loading-state" style="grid-column: 1/-1"><div class="spinner"></div><p>Loading pending reviews...</p></div>';
            
            // Fetch registry history
            const response = await fetch('/api/mods');
            if (response.ok) {
                allMods = await response.json();
                renderModsList(allMods);
            }
            
            // Fetch staging
            const stagingResponse = await fetch('/api/mods/staging');
            if (stagingResponse.ok) {
                const staging = await stagingResponse.json();
                renderStagingList(staging);
            }
            
        } catch (error) {
            modsListEl.innerHTML = `<div class="loading-state" style="grid-column: 1/-1; color: #ef4444;"><i class="fa-solid fa-circle-exclamation" style="font-size: 24px; margin-bottom: 12px;"></i><p>Failed to load mods.</p></div>`;
            console.error('Error fetching mods:', error);
        }
    }

    function renderStagingList(staging) {
        stagingListEl.innerHTML = '';
        if (staging.length === 0) {
            stagingListEl.innerHTML = '<div class="loading-state" style="grid-column: 1/-1"><p>No pending reviews right now.</p></div>';
            return;
        }

        staging.forEach(item => {
            const card = document.createElement('div');
            card.className = 'article-card';
            card.style.borderColor = '#f59e0b';
            
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                    <div class="article-title" style="margin-bottom: 0; font-size: 18px; color: #fff;">${item.meta.name} (v${item.meta.version})</div>
                    <span style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase;">
                        Pending
                    </span>
                </div>
                <div class="article-meta" style="margin-bottom: 8px;">
                    <span><i class="fa-solid fa-file-lines" style="margin-right: 4px;"></i> ${item.sub.original_filename}</span>
                </div>
                <div class="article-meta" style="margin-bottom: 12px;">
                    <span><i class="fa-solid fa-user" style="margin-right: 4px;"></i> ${item.sub.submitted_by}</span>
                </div>
                
                <div style="display: flex; gap: 8px; margin-top: 16px;">
                    <button class="approve-btn" data-id="${item.id}" style="flex: 1; background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #10b981; padding: 8px; border-radius: 6px; cursor: pointer; font-weight: 600; transition: all 0.2s;"><i class="fa-solid fa-check"></i> Approve</button>
                    <button class="reject-btn" data-id="${item.id}" style="flex: 1; background: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; color: #ef4444; padding: 8px; border-radius: 6px; cursor: pointer; font-weight: 600; transition: all 0.2s;"><i class="fa-solid fa-xmark"></i> Reject</button>
                </div>
            `;
            
            stagingListEl.appendChild(card);
        });

        // Add event listeners for action buttons
        document.querySelectorAll('.approve-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const sid = e.currentTarget.dataset.id;
                e.currentTarget.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Deploying...';
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
            btn.addEventListener('click', async (e) => {
                const sid = e.currentTarget.dataset.id;
                const reason = prompt("Enter reason for rejection:");
                if (reason === null) return; // Cancelled
                
                e.currentTarget.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Rejecting...';
                e.currentTarget.disabled = true;
                
                const res = await fetch(`/api/mods/reject/${sid}`, { 
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason })
                });
                const result = await res.json();
                if (result.success) {
                    fetchMods();
                } else {
                    alert('Rejection failed: ' + result.error);
                }
            });
        });
    }

    function renderModsList(mods) {
        modsListEl.innerHTML = '';
        const modNames = Object.keys(mods);
        
        if (modNames.length === 0) {
            modsListEl.innerHTML = '<div class="loading-state" style="grid-column: 1/-1"><p>No mods found in registry.</p></div>';
            return;
        }

        modNames.forEach(modName => {
            const mod = mods[modName];
            const card = document.createElement('div');
            card.className = 'article-card';
            
            // Determine status color
            let statusColor = '#94a3b8';
            if (mod.status === 'deployed') statusColor = '#10b981';
            else if (mod.status === 'pending_review') statusColor = '#f59e0b';
            else if (mod.status === 'rejected') statusColor = '#ef4444';
            
            // Get last updated time
            const history = mod.history || [];
            const lastUpdate = history.length > 0 ? history[history.length - 1].submitted_at : '';

            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                    <div class="article-title" style="margin-bottom: 0; font-size: 18px; color: #fff;">${modName}</div>
                    <span style="background: ${statusColor}33; color: ${statusColor}; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid ${statusColor}55;">
                        ${mod.status.replace(/_/g, ' ')}
                    </span>
                </div>
                <div class="article-meta" style="margin-bottom: 8px;">
                    <span><i class="fa-solid fa-file-lines" style="margin-right: 4px;"></i> ${mod.current_filename || 'Unknown file'}</span>
                </div>
                <div class="article-meta" style="margin-bottom: 8px;">
                    <span><i class="fa-solid fa-user" style="margin-right: 4px;"></i> ${mod.submitted_by || 'Unknown'}</span>
                </div>
                <div class="article-snippet" style="font-family: monospace; font-size: 11px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px; word-break: break-all;">
                    ${mod.current_hash ? mod.current_hash.substring(0, 16) + '...' : 'No hash'}
                </div>
                <div class="article-meta" style="margin-bottom: 0; margin-top: 12px; justify-content: flex-end;">
                    <span>${formatDate(lastUpdate)}</span>
                </div>
            `;
            
            modsListEl.appendChild(card);
        });
    }

    refreshModsBtn.addEventListener('click', () => {
        const icon = refreshModsBtn.querySelector('i');
        icon.style.animation = 'spin 1s linear infinite';
        fetchMods().then(() => {
            setTimeout(() => icon.style.animation = '', 500);
        });
    });

    // Helper: format datetime string
    function formatDate(dateStr) {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            if (isNaN(date.getTime())) return dateStr;
            
            return new Intl.DateTimeFormat('en-US', { 
                month: 'short', 
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            }).format(date);
        } catch(e) {
            return dateStr;
        }
    }

    // Initial load
    fetchArticles();
});
