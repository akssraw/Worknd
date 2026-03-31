##🛡️Worknd: Live Subtitle HUD

Worknd is a sleek, real-time "Social Continuity" HUD (Heads-Up Display). It’s designed as a fun utility for anyone who spends a lot of time in headphones. Whether you’re gaming, coding, or just vibing to music, worknd listens to the world around you and floats a live transcript on your screen so you never miss a beat.

Think of it as "Real-World Subtitles" for your desktop.

##✨ Key Features:-

-🎧 Social Bridge: Catch what people are saying without having to pause your music or pull off your headset.

-🇮🇳 Native Hinglish Support: Powered by Sarvam AI (saaras:v3), it handles the natural mix of Hindi and English flawlessly.

-🪟 Ghost Overlay: A borderless, "click-through" UI. It floats on top of your apps but stays invisible to your mouse, so it never interrupts your clicks.

-🤏 Interactive HUD: Fully draggable. Double-click to snap the HUD to the Left, Center, or Right of your screen.

-⚡ Smooth Flow: Built with a custom anti-flicker engine, the text updates only when there's something meaningful to show, keeping your workspace clean.

##🛠️ Setup & Installation
1. Prerequisites
-Python 3.8 or higher.

-A Sarvam AI API Key.

2. Install Dependencies
Run this in your terminal:

##Bash
pip install pyaudio httpx numpy
Note: If PyAudio gives you trouble on Windows, try installing it via conda or a pre-compiled wheel.

3. Set Your API Key 🔑
To keep your credentials safe, worknd looks for your key in your environment variables:

Windows (PowerShell):

PowerShell
$env:SARVAM_API_KEY='your_api_key_here'
Windows (Command Prompt):

DOS
set SARVAM_API_KEY=your_api_key_here
Linux/macOS:

Bash
export SARVAM_API_KEY='your_api_key_here'
🚀 How to Run
Open your terminal in the project folder.

##Launch the script:

Bash
python worknd.py
A transparent "pill" will appear. Start talking, and watch the subtitles roll in!

🎮 Controls
Drag: Click and hold to move the HUD.

Snap: Double-click to cycle through screen positions.

Quit: Hit Esc or click the × icon.

📜 License
MIT License - Created by Aksshat Singh Rawat.
