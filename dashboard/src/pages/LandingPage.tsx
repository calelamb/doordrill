import { Link } from "react-router-dom";

export function LandingPage() {
  return (
    <div className="bg-background font-sans text-ink selection:bg-accent/30 min-h-screen relative overflow-hidden">
      {/* TopAppBar */}
      <nav className="fixed top-0 w-full z-50 bg-white/70 backdrop-blur-xl shadow-sm shadow-accent/5">
        <div className="flex items-center justify-between px-6 py-4 max-w-7xl mx-auto">
          <div className="flex items-center gap-2">
            <svg
              className="text-accent w-6 h-6"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
            <span className="text-xl font-extrabold text-accent tracking-tighter font-display">DoorDrill</span>
          </div>
          <div className="flex items-center gap-4">
            <Link
              to="/login"
              className="text-muted font-medium text-sm hover:text-accent-hover transition-colors duration-300"
            >
              Login
            </Link>
            <Link
              to="/login"
              className="bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-lg text-sm font-semibold transition-all hover:-translate-y-0.5"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      <main className="pt-24 pb-12 overflow-hidden">
        {/* Hero Section */}
        <section className="relative px-6 pt-12 pb-24 max-w-7xl mx-auto flex flex-col items-center text-center">
          <div className="absolute top-0 -z-10 w-full h-[600px] bg-[radial-gradient(circle_at_50%_0%,_#d3e8d5_0%,_transparent_70%)] opacity-40"></div>
          
          <span className="inline-block px-4 py-1.5 mb-6 text-[10px] uppercase tracking-widest font-bold text-accent bg-accent/10 rounded-full">
            AI-Powered Training
          </span>
          
          <h1 className="font-display text-5xl md:text-7xl font-extrabold tracking-tight text-ink leading-[1.1] mb-8">
            Master the Art <br className="hidden md:block" /> of the Knock
          </h1>
          
          <p className="max-w-2xl text-muted text-lg md:text-xl leading-relaxed mb-10">
            Train with our world-class AI on your own materials, get real-time feedback, and dominate your next door.
          </p>
          
          <div className="flex flex-col sm:flex-row gap-4 mb-20 w-full sm:w-auto">
            <Link
              to="/login"
              className="bg-gradient-to-br from-accent to-accent-hover text-white px-8 py-4 rounded-xl font-bold text-lg shadow-[0_20px_50px_rgba(45,90,61,0.25)] hover:-translate-y-1 transition-all duration-300"
            >
              Start Training With DoorDrill
            </Link>
            <button className="px-8 py-4 rounded-xl font-bold text-lg border border-border-strong text-accent-hover bg-white/50 hover:bg-white transition-colors">
              View Demo
            </button>
          </div>

          {/* Floating Visual */}
          <div className="relative w-full max-w-4xl mx-auto mt-4 group">
            <div className="absolute -inset-4 bg-gradient-to-tr from-accent/20 to-accent-soft/40 blur-3xl opacity-30 rounded-full"></div>
            <div className="bg-white/70 backdrop-blur-2xl rounded-[24px] border border-white shadow-[0_40px_100px_rgba(45,90,61,0.06)] p-2 md:p-4 overflow-hidden">
              <img
                alt="Sales Coaching Dashboard"
                className="rounded-xl w-full shadow-inner grayscale-[20%] group-hover:grayscale-0 transition-all duration-700"
                src="/img/showcase/performance_panel.png"
              />
            </div>
            
            {/* Floating Elements */}
            <div className="absolute -right-4 -bottom-8 md:-right-10 md:bottom-12 bg-white/80 backdrop-blur-xl p-4 rounded-xl border border-white/60 shadow-xl hidden sm:flex items-center gap-4 hover:shadow-2xl hover:-translate-y-1 transition-all duration-300">
              <div className="w-10 h-10 rounded-full bg-accent flex items-center justify-center">
                <svg className="text-white w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" /></svg>
              </div>
              <div className="text-left">
                <p className="text-xs font-bold text-accent">AI Coach</p>
                <p className="text-[10px] text-muted">Improving objection handling...</p>
              </div>
            </div>
          </div>
        </section>

        {/* Feature Grid (What We Do) */}
        <section className="bg-white/40 border-y border-border/50 py-24 px-6 relative">
          <div className="max-w-7xl mx-auto">
            <div className="mb-16">
              <h2 className="font-display text-3xl font-bold text-ink mb-4">Precision-Engineered Training</h2>
              <div className="h-1.5 w-12 bg-accent rounded-full"></div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {/* Card 1 */}
              <div className="bg-white/80 backdrop-blur-xl p-8 rounded-[24px] shadow-[0_4px_20px_rgba(45,90,61,0.03)] border border-white hover:shadow-xl hover:-translate-y-1 transition-all duration-300">
                <div className="w-14 h-14 bg-accent/10 rounded-2xl flex items-center justify-center mb-6 text-accent">
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
                </div>
                <h3 className="font-display text-xl font-bold mb-3 text-ink">AI Roleplay</h3>
                <p className="text-muted leading-relaxed">
                  Practice pitches with realistic, objecting AI personas. From the skeptic to the busy executive, train for every scenario.
                </p>
              </div>
              {/* Card 2 */}
              <div className="bg-white/80 backdrop-blur-xl p-8 rounded-[24px] shadow-[0_4px_20px_rgba(45,90,61,0.03)] border border-white hover:shadow-xl hover:-translate-y-1 transition-all duration-300">
                <div className="w-14 h-14 bg-accent/10 rounded-2xl flex items-center justify-center mb-6 text-accent">
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
                </div>
                <h3 className="font-display text-xl font-bold mb-3 text-ink">Real-Time Feedback</h3>
                <p className="text-muted leading-relaxed">
                  Get instant analytics on tone, pacing, and objection handling. Turn every knock into a learning opportunity immediately.
                </p>
              </div>
              {/* Card 3 */}
              <div className="bg-white/80 backdrop-blur-xl p-8 rounded-[24px] shadow-[0_4px_20px_rgba(45,90,61,0.03)] border border-white hover:shadow-xl hover:-translate-y-1 transition-all duration-300">
                <div className="w-14 h-14 bg-accent/10 rounded-2xl flex items-center justify-center mb-6 text-accent">
                  <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" /></svg>
                </div>
                <h3 className="font-display text-xl font-bold mb-3 text-ink">Manager Analytics</h3>
                <p className="text-muted leading-relaxed">
                  Track your team's pitch quality at scale. Identify top performers and coach those who need it with data-driven insights.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Timeline (How to Get Started) */}
        <section className="py-24 px-6 max-w-7xl mx-auto">
          <div className="text-center mb-20">
            <h2 className="font-display text-4xl font-extrabold text-ink mb-6">From Newbie to Closer</h2>
            <p className="text-muted max-w-xl mx-auto text-lg">Our streamlined onboarding process gets your team ready for the field in minutes, not weeks.</p>
          </div>
          
          <div className="relative">
            {/* Vertical Line */}
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border-strong hidden md:block"></div>
            
            <div className="space-y-24">
              {/* Step 1 */}
              <div className="flex flex-col md:flex-row items-center gap-12 group">
                <div className="flex-1 md:text-right order-2 md:order-1">
                  <h3 className="font-display text-2xl font-bold text-ink mb-4">1. Upload Materials</h3>
                  <p className="text-muted leading-relaxed text-lg">
                    Simply drop your PDFs, slide decks, or pitch scripts into our AI engine. We'll analyze your specific value props and objections.
                  </p>
                </div>
                <div className="z-10 w-14 h-14 rounded-full bg-accent flex items-center justify-center text-white font-bold ring-8 ring-background order-1 md:order-2 shadow-lg">
                  01
                </div>
                <div className="flex-1 order-3">
                  <div className="p-4 bg-white/60 backdrop-blur-md rounded-3xl border border-white/50 shadow-xl group-hover:-translate-y-2 transition-transform duration-500">
                    <img alt="Upload files interface" className="rounded-2xl" src="/img/showcase/upload_document.png" />
                  </div>
                </div>
              </div>
              
              {/* Step 2 */}
              <div className="flex flex-col md:flex-row items-center gap-12 group">
                <div className="flex-1 order-3 md:order-1">
                  <div className="p-4 bg-white/60 backdrop-blur-md rounded-3xl border border-white/50 shadow-xl group-hover:-translate-y-2 transition-transform duration-500">
                    <img alt="AI Practice UI" className="rounded-2xl" src="/img/showcase/live_practice.png" />
                  </div>
                </div>
                <div className="z-10 w-14 h-14 rounded-full bg-accent flex items-center justify-center text-white font-bold ring-8 ring-background order-1 md:order-2 shadow-lg">
                  02
                </div>
                <div className="flex-1 md:text-left order-2 md:order-3">
                  <h3 className="font-display text-2xl font-bold text-ink mb-4">2. Practice with AI</h3>
                  <p className="text-muted leading-relaxed text-lg">
                    Use our mobile app to run unlimited voice-based roleplays. The AI responds dynamically based on your uploaded sales methodology.
                  </p>
                </div>
              </div>
              
              {/* Step 3 */}
              <div className="flex flex-col md:flex-row items-center gap-12 group">
                <div className="flex-1 md:text-right order-2 md:order-1">
                  <h3 className="font-display text-2xl font-bold text-ink mb-4">3. Dominate the Doors</h3>
                  <p className="text-muted leading-relaxed text-lg">
                    Hit the field with confidence. Use our real-time coaching snippets when you encounter tough objections and watch your close rate soar.
                  </p>
                </div>
                <div className="z-10 w-14 h-14 rounded-full bg-accent flex items-center justify-center text-white font-bold ring-8 ring-background order-1 md:order-2 shadow-lg">
                  03
                </div>
                <div className="flex-1 order-3">
                  <div className="p-4 bg-accent/5 backdrop-blur-md rounded-3xl border border-accent/20 shadow-xl overflow-hidden relative group-hover:-translate-y-2 transition-transform duration-500">
                    <div className="flex flex-col items-center py-12 text-accent">
                      <svg className="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" /></svg>
                      <p className="font-display text-2xl font-bold">Close 40% More</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Final CTA */}
        <section className="py-24 px-6 relative">
          <div className="max-w-5xl mx-auto bg-accent rounded-[32px] p-12 md:p-20 text-center relative overflow-hidden shadow-2xl shadow-accent/20">
            <div className="absolute inset-0 bg-gradient-to-br from-accent-hover to-accent opacity-90"></div>
            <div className="absolute -top-40 -left-40 w-96 h-96 bg-white/10 rounded-full blur-3xl"></div>
            <div className="absolute -bottom-40 -right-40 w-96 h-96 bg-accent-soft/10 rounded-full blur-3xl"></div>
            
            <div className="relative z-10">
              <h2 className="font-display text-4xl md:text-6xl font-extrabold text-white mb-8 tracking-tight">Ready to revolutionize your sales team?</h2>
              <Link
                to="/login"
                className="inline-block bg-white text-accent-hover px-10 py-5 rounded-2xl font-bold text-xl hover:bg-background transition-colors shadow-2xl hover:shadow-white/20 hover:-translate-y-1"
              >
                Start Training With DoorDrill
              </Link>
              <p className="mt-8 text-white/80 font-medium text-lg">Join 500+ teams winning more doors today.</p>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="w-full pt-20 pb-10 bg-white/50 border-t border-border/50 backdrop-blur-md">
        <div className="flex flex-col md:flex-row justify-between items-center px-8 space-y-8 md:space-y-0 max-w-7xl mx-auto">
          <div className="flex flex-col items-center md:items-start gap-2">
            <div className="flex items-center gap-2">
              <svg className="text-accent w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" /></svg>
              <span className="text-lg font-extrabold text-ink font-display tracking-tight">DoorDrill</span>
            </div>
            <p className="text-muted text-sm text-center md:text-left">The intelligence layer for field sales teams.</p>
          </div>
          <div className="flex flex-wrap justify-center gap-8">
            <a className="text-muted font-sans text-sm hover:text-accent font-medium transition-colors" href="#">How it Works</a>
            <a className="text-muted font-sans text-sm hover:text-accent font-medium transition-colors" href="#">Features</a>
            <a className="text-muted font-sans text-sm hover:text-accent font-medium transition-colors" href="#">Contact Us</a>
            <a className="text-muted font-sans text-sm hover:text-accent font-medium transition-colors" href="#">Privacy Policy</a>
          </div>
        </div>
        <div className="mt-12 text-center text-muted/60 text-xs font-medium">
          © 2024 DoorDrill AI. All rights reserved.
        </div>
      </footer>
    </div>
  );
}
