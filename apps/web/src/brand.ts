export const BRAND = {
  name: "Arogya Drishti",
  tagline: "See the warning signs before they become emergencies.",
  disclaimer: "Clinical decision support only. Not for medical diagnosis.",
} as const;

// External video consultation service (SparkMeet). Configure with VITE_SPARKMEET_URL; opened in a new tab only,
// never with patient identifiers, names or session tokens in the URL.
export const SPARKMEET_URL: string = (import.meta.env.VITE_SPARKMEET_URL as string | undefined) || "https://sparkmeet-web.onrender.com/";
