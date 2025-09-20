import axios, { AxiosInstance } from 'axios';

export class SpecifyClient {
  private api: AxiosInstance;

  constructor(apiToken: string) {
    this.api = axios.create({
      baseURL: 'https://api.specify.org/v1',
      headers: {
        'Authorization': `Bearer ${apiToken}`,
        'Content-Type': 'application/json'
      }
    });
  }

  async getTaxonomy(id: string) {
    const response = await this.api.get(`/taxonomy/${id}`);
    return response.data;
  }

  async createTaxonomy(data: any) {
    const response = await this.api.post('/taxonomy', data);
    return response.data;
  }

  async updateTaxonomy(id: string, data: any) {
    const response = await this.api.put(`/taxonomy/${id}`, data);
    return response.data;
  }

  async searchTaxonomy(query: string) {
    const response = await this.api.get(`/taxonomy/search?q=${encodeURIComponent(query)}`);
    return response.data;
  }
}
