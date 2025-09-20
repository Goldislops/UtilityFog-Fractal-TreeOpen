import { SpecifyClient } from './client';
import { MockSpecifyClient } from './mock-client';

export class SpecifyTool {
  private client: SpecifyClient | MockSpecifyClient;

  constructor() {
    const isLiveMode = process.env.SPECIFY_API_TOKEN !== undefined;
    
    if (isLiveMode) {
      console.log('🔴 LIVE MODE: Using real Specify API');
      this.client = new SpecifyClient(process.env.SPECIFY_API_TOKEN!);
    } else {
      console.log('🟡 MOCK MODE: Using mock responses');
      this.client = new MockSpecifyClient();
    }
  }

  async getTaxonomy(id: string) {
    return this.client.getTaxonomy(id);
  }

  async createTaxonomy(data: any) {
    return this.client.createTaxonomy(data);
  }

  async updateTaxonomy(id: string, data: any) {
    return this.client.updateTaxonomy(id, data);
  }
}

export { SpecifyClient, MockSpecifyClient };
