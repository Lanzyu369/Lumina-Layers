function LoadingSpinner() {
  return (
    <div
      data-testid="loading-spinner"
      className="absolute inset-0 flex items-center justify-center bg-slate-950"
    >
      <div className="relative flex items-center justify-center p-4">
        <div className="relative flex h-16 w-16 items-center justify-center">
          <div className="absolute inset-0 rounded-full border border-blue-500/30" />
          <div className="absolute inset-0 rounded-full border-t-2 border-r-2 border-blue-400 rotate-45 opacity-80 animate-glow-spin" />
          <div className="h-3 w-3 rounded-full bg-blue-400" />
        </div>
      </div>
    </div>
  );
}

export default LoadingSpinner;
