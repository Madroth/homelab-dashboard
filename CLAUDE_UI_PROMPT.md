Please design a modern, premium web interface for my "Homelab Media Curator Dashboard". This application is a self-hosted media management tool that automatically intercepts, identifies, and sorts downloaded media files (Movies, TV Shows, Audiobooks, Ebooks, Comics) into my Plex/Jellyfin library using AI.

I need a complete UI mockup (HTML/CSS/JS or React/Tailwind) that incorporates both the features I currently have, and the future features I plan to implement. 

### 1. Current Dashboard Interface & Controls
The current UI is functional but needs a visual overhaul. It must include:
*   **Split Views/Tabs:** A way to toggle between a "Curated" list (items successfully auto-sorted) and a "Pending" queue (items flagged for manual human review because the AI was unsure).
*   **Media Cards:** Each processed file is displayed as a card showing its proposed title, media type, and timestamp.
*   **Interactive Details Modal:** Clicking a media card opens a detailed modal containing:
    *   Original filename vs. target library path.
    *   Short and long AI-generated plot/book descriptions.
    *   Franchise/series groupings.
    *   The internal logic/reasoning the AI used to sort it.
*   **Control Buttons (Inside Modal):**
    *   **Reclassify Dropdown:** Instantly changes the media category (e.g., Movie to TV Show) and automatically moves the file.
    *   **Edit Title:** Allows the user to manually correct the title for pending items before approval.
    *   **Reject/Delete:** Trashes the media item and deletes the source file from the server.
    *   **Approve:** Manually pushes a pending item into the library.

### 2. Future Feature Roadmap (Please integrate these into the design)
I am expanding the dashboard. Please visually incorporate these 10 new features into the layout:
1.  **Cover Art & Thumbnails:** Display movie posters, book covers, or comic art on the media cards.
2.  **Advanced Search & Filters:** A top search bar and filter toggles (e.g., by Media Type, Year, Recently Added).
3.  **Bulk Actions:** Checkboxes on media cards with a floating action bar to bulk-approve, reject, or reclassify items.
4.  **Undo / Rollback Button:** A prominent "Undo" action inside the details modal to pull a filed item back to the drop zone.
5.  **In-Browser Media Previews:** A visual space inside the modal for an HTML5 audio/video preview player.
6.  **Drag-and-Drop Upload Zone:** A designated UI area (or persistent drop target) to manually drag files from the desktop to the server.
7.  **Duplicate Resolution Center:** A dedicated alert or split-view UI for handling version collisions (e.g., picking between a 1080p and 4K file of the same movie).
8.  **Disk Space & Status Widgets:** A persistent sidebar or header widget showing remaining storage space (e.g., a sleek progress bar) and the real-time status of the background daemon (Idle/Processing).
9.  **Custom Tagging:** An input field in the modal to add custom tags (e.g., "Holiday", "Kids") that sync to Plex collections.
10. **Live Daemon Audit Log:** A collapsible drawer or sidebar showing a live terminal-style feed of background processing events.

### 3. External Services & *Arr Stack Integrations
The Media Curator dashboard should act as a central hub. Please include a persistent navigation sidebar, a dropdown menu, or an elegant "Quick Links" widget block that provides one-click access to my underlying homelab services. 

Please visually incorporate links for the following tools, ideally with their brand colors or matching sleek minimalist icons:

**Media Servers:**
*   **Plex / Jellyfin**: For watching the final curated media.
**The *Arr Stack (Automation):**
*   **Radarr**: Movie automation and tracking.
*   **Sonarr**: TV Show automation and tracking.
*   **Readarr**: Ebook and Audiobook tracking.
*   **Lidarr**: Music tracking.
*   **Prowlarr**: Indexer manager.
**Download Clients:**
*   **qBittorrent / Deluge**: Torrent management.
*   **SABnzbd / NZBGet**: Usenet management.

**Design Note for Links:** 
These shouldn't just look like a basic list of hyperlinks. Try designing them as a grid of sleek, glassmorphic app-icon tiles in the sidebar, or as a collapsible "Services Hub" drawer that slides out when needed, keeping the main UI focused on the curation queue.

### 4. Design Instructions
*   **Aesthetic:** Go for a sleek, premium, "Homelab / Self-Hosted" aesthetic. Think dark mode by default, glassmorphism, vibrant accent colors (like neon purples, deep blues, or electric greens), and smooth rounded corners.
*   **Layout:** Consider a sidebar-based layout for navigation (Queue, Library, Uploads, Settings, Quick Links) with a top header for search/filtering, and a main content area for a responsive grid of media cards.
*   **Micro-interactions:** Include hover states for cards, smooth transitions for modals, and clear visual hierarchy.
*   **No Placeholders:** Generate realistic placeholder text and image placeholders (using unsplash or similar) so the design feels alive.
*   **Output:** Please provide the full functional code (e.g., a single-file React component using Tailwind CSS, or Vanilla HTML/CSS) so I can preview it immediately in Artifacts.
