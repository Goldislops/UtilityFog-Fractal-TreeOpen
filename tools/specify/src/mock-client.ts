export class MockSpecifyClient {
  private mockData = {
    taxonomies: {
      '1': {
        id: '1',
        name: 'Utility Fog Taxonomy',
        description: 'Mock taxonomy for development',
        version: '0.1.0',
        created_at: '2025-09-20T00:00:00Z'
      }
    }
  };

  async getTaxonomy(id: string) {
    await this.simulateDelay();
    const taxonomy = this.mockData.taxonomies[id as keyof typeof this.mockData.taxonomies];
    if (!taxonomy) {
      throw new Error(`Taxonomy ${id} not found`);
    }
    return taxonomy;
  }

  async createTaxonomy(data: any) {
    await this.simulateDelay();
    const newId = String(Object.keys(this.mockData.taxonomies).length + 1);
    const newTaxonomy = {
      id: newId,
      ...data,
      created_at: new Date().toISOString()
    };
    this.mockData.taxonomies[newId as keyof typeof this.mockData.taxonomies] = newTaxonomy;
    return newTaxonomy;
  }

  async updateTaxonomy(id: string, data: any) {
    await this.simulateDelay();
    const existing = this.mockData.taxonomies[id as keyof typeof this.mockData.taxonomies];
    if (!existing) {
      throw new Error(`Taxonomy ${id} not found`);
    }
    const updated = {
      ...existing,
      ...data,
      updated_at: new Date().toISOString()
    };
    this.mockData.taxonomies[id as keyof typeof this.mockData.taxonomies] = updated;
    return updated;
  }

  async searchTaxonomy(query: string) {
    await this.simulateDelay();
    const results = Object.values(this.mockData.taxonomies).filter(
      taxonomy => taxonomy.name.toLowerCase().includes(query.toLowerCase())
    );
    return { results, total: results.length };
  }

  private async simulateDelay() {
    // Simulate network delay
    await new Promise(resolve => setTimeout(resolve, 100 + Math.random() * 200));
  }
}
