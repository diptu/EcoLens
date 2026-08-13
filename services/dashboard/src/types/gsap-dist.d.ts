// Type declaration for the gsap direct-import path
// (avoids gsap's "sideEffects": false tree-shaking issue)
declare module "gsap/dist/gsap.js" {
  import gsap from "gsap";
  export default gsap;
}

declare module "gsap/dist/ScrollTrigger.js" {
  import { ScrollTrigger } from "gsap/ScrollTrigger";
  export { ScrollTrigger };
}
