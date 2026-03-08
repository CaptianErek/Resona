document.addEventListener("DOMContentLoaded", () => {
    const videoContainer = document.getElementById("VideoContainer");
    const mainContent = document.getElementById("main-content");
    const loadingScreen = document.getElementById("loading-screen");

    if (!videoContainer || !mainContent || !loadingScreen) {
        console.error("Required elements not found");
        return;
    }

    const video = document.createElement("video");
    video.src = "Videos/Initial Video.mp4";
    video.muted = true;
    video.playsInline = true;
    // Removed autoplay = true
    
    // Style to ensure video takes up space properly
    videoContainer.style.position = "fixed";
    videoContainer.style.top = "0";
    videoContainer.style.left = "0";
    videoContainer.style.width = "100%";
    videoContainer.style.height = "100%";
    videoContainer.style.zIndex = "9999";
    videoContainer.style.backgroundColor = "black"; 
    
    video.style.width = "100%";
    video.style.height = "100%";
    video.style.objectFit = "cover";

    videoContainer.appendChild(video);

    // Loading Loading Logic
    let progress = 0;
    const updateLoading = () => {
        // Random increment for realistic feel
        const increment = Math.floor(Math.random() * 2) + 1; 
        progress = Math.min(progress + increment, 100);
        
        loadingScreen.textContent = `${progress}%`;

        if (progress < 100) {
            requestAnimationFrame(() => setTimeout(updateLoading, 30)); 
        } else {
            // Loading Complete
            loadingScreen.style.opacity = '0';
            setTimeout(() => {
                loadingScreen.style.display = 'none';
                video.play().catch(e => console.error("Video play failed:", e));
            }, 500); // Wait for fade out
        }
    };
    
    // Start loading immediately
    updateLoading();

    let switched = false;

    const showContent = () => {
        if (switched) return;
        switched = true;
        
        video.pause();
        videoContainer.style.display = "none";
        mainContent.style.display = "block";
        mainContent.classList.add("roll-in");
    };

    video.addEventListener("timeupdate", () => {
        const currentTime = video.currentTime;
        
        // Fade out logic starting at 5 seconds
        if (currentTime >= 5 && currentTime < 7) {
            const fadeDuration = 2; // 7 - 5
            const timeElapsedInFade = currentTime - 5;
            const opacity = 1 - (timeElapsedInFade / fadeDuration);
            videoContainer.style.opacity = opacity;
        }

        if (currentTime >= 7) {
            showContent();
        }
    });

    // Backup timer logic needs to depend on video start, so we attach it to 'play' event
    video.addEventListener('play', () => {
        setTimeout(showContent, 7500);
    });

    // CRITICAL: If video errors (file missing, codec issue, etc.) show content immediately
    video.addEventListener('error', () => {
        console.warn("Video failed to load, skipping intro.");
        showContent();
    });

    // ABSOLUTE fallback: always show content after 10s regardless of video state
    setTimeout(showContent, 10000);
});