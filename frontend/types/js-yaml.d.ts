declare module 'js-yaml' {
  export function load(str: string | null | undefined, opts?: any): any
  export function dump(obj: any, opts?: any): string
}

